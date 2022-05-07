#
# Delete builds in buildType
import os
import platform
import logging
import datetime as dt
import pytz
import requests
import pyodbc
import contextlib
import json
import logutil
import argparse
from TCConfig import TCConfig

TCLM_VERSION = 'TCLM Version -99 '


class LicenseDB:
    def __init__(self, tcc: TCConfig):
        # Connect to DB
        conn_dict = tcc.get_lmdb_config()
        self.connection = pyodbc.connect(**conn_dict)
        self.generation_date = tcc.get_generation_date()

    '''
    Reserve one license from the license manager, returns the license string
    '''

    def reserve_license(self, instance_url):
        params = []
        sql = f"""
        UPDATE License2019DEV 
        SET tc_instance= '{instance_url}'
        OUTPUT INSERTED.license_key
        WHERE license_key in 
            (SELECT license_key 
             FROM License2019DEV  
             WHERE license_key IN 
                 (SELECT MAX(license_key) 
                  FROM License2019DEV 
                  WHERE tc_instance='' and floating_license=1 and generation_date='{self.generation_date}'))
        """
        # print(sql)
        rows = self.sql_query(sql, params)
        if len(rows) == 0:
            logging.error(f'Query returned 0 rows. No Licenses available to reserve for: {instance_url}')
        else:
            logging.info(f'One license reserved for: {instance_url}')
        return rows[0].license_key

    # todo fix it so we dont need to sepcify the license to be released back
    def release_license(self, instance_url):
        params = []
        sql = f"""
        UPDATE License2019DEV 
        SET tc_instance= ''
        OUTPUT INSERTED.license_key
        WHERE license_key in 
            (SELECT license_key 
             FROM License2019DEV  
             WHERE license_key IN 
                 (SELECT MAX(license_key) 
                  FROM License2019DEV 
                  WHERE tc_instance='' and floating_license=1 and generation_date='{self.generation_date}'))
        """

        rows = self.sql_query(sql, params)
        if len(rows) == 0:
            logging.error(f'Query returned 0 rows returned, Failed to release license key from LMDB. ')
        else:
            logging.info(f'Released license key {rows[0].license_key} reserved by: {instance_url}')
        return rows[0].license_key

    def obsolete_licenses_in_db(self, fromdate):
        pass

    def available_licenses_in_db(self):
        sql = "SELECT COUNT(*) as total_licenses FROM license2019DEV WHERE tc_instance = ''"
        params = []
        rows = self.sql_query(sql, params)
        available_licenses = rows[0].total_licenses + 2  # Add two for one multi agent licsens of 3
        logging.info(f'Available licenses in LMDB for Generation Date:{self.generation_date} = {available_licenses}')
        return available_licenses

    def sql_query(self, sql, params):
        logging.info("Connecting to DB...")
        with contextlib.closing(self.connection.cursor()) as cur:
            logging.info("Executing query")
            cur.execute(sql, params)
            logging.info("Fetching rows")
            all_rows = cur.fetchall()
            self.connection.commit()
        return all_rows


class TCInstance:
    def __init__(self, tcc: TCConfig, instance):
        self.tc_instance = tcc.get_tc_config(instance)
        self.url = self.tc_instance["uri"]
        self.base_url = self.tc_instance["uri"] + '/httpAuth/app/rest/'
        self.auth = self.tc_instance['auth']
        self.header = {'Content-Type': 'application/xml', 'Accept': 'application/json'}
        self.idle_days = self.tc_instance['idle_days']
        self.license_buffer_size = self.tc_instance['license_buffer_size']

    def getConnectedAgents(self):
        api_s = f'{self.base_url}agents?includeDisconnected=false'
        logging.info(f'getConnectedAgents({api_s})')
        r = requests.get(api_s, headers=self.header, auth=(self.auth[0], self.auth[1]))
        response_json = json.loads(r.content.decode('utf-8'))
        agent_list = [item['name'] for item in response_json.get('agent')]
        logging.info(f'Number of Connected Agents: {len(agent_list)}')
        return agent_list

    # Sending in a count:1 as a parameter, we are able to get the very last build info for the agent
    # we use that info to determine when the agent was active last
    def getAgentDetails(self, agent_name):
        header = {'Content-Type': 'application/json'}
        api_s = f'{self.base_url}builds?locator=agentName:{agent_name},count:1'
        logging.info(f'getAgentDetails({agent_name})')
        response_json = None
        try:
            r = requests.get(api_s, headers=self.header, auth=(self.auth[0], self.auth[1]))
            response_json = json.loads(r.content.decode('utf-8'))
        except requests.exceptions.RequestException as e:
            logging.info(f'Error ({e}) getAgentDetails({api_s})')
            raise SystemExit(e)
        return response_json

    def getAgentIdleDays(self, agent_name):
        ldate = None
        cdate = None
        id = None
        try:
            adetails = self.getAgentDetails(agent_name)
            if adetails.get('count') != 0:  # If the count is 0 there is no build
                finishdate = adetails.get('build')[0]['finishOnAgentDate']
                id = adetails.get('build')[0]['id']
                ldate = dt.datetime.strptime(finishdate, '%Y%m%dT%H%M%S%z')
                cdate = dt.datetime.now(pytz.utc)
                delta = cdate - ldate
                idays = delta.days
            else:
                idays = -1
        except requests.exceptions.RequestException as e:
            logging.error(f'Error {e} on getting Agent details for {agent_name}')
            idays = 0

        logging.info(f'Agent: {agent_name} Build ID: {id} Last Build: {ldate} Current Date: {cdate} Idle Days: {idays}')
        return idays

    # todo Handle status from API calls & Catch exceptions
    def revokeAgentAuthorization(self, agent_name):
        api_s = f'{self.base_url}agents/{agent_name}/authorized'
        logging.info(f'revokeAgentAuthorization({agent_name})')
        h = {'Content-Type': 'text/plain'}
        r = None
        try:
            r = requests.put(api_s, headers=h, data='false', auth=(self.auth[0], self.auth[1]))
            logging.info(f'Agent Revocation Call Status: {r.status_code}')
        except requests.exceptions.RequestException as e:
            logging.info(f'Error({e}) in making a Rest Call to : {api_s}')
        return r

    def get_licenseData(self):
        api_s = f'{self.base_url}server/licensingData'
        logging.info(f'get_licenseData()')

        r = requests.get(api_s, headers=self.header, auth=(self.auth[0], self.auth[1]))
        response_json = json.loads(r.content.decode('utf-8'))

        max_agents = response_json['maxAgents']
        agents_left = response_json['agentsLeft']
        license_count = response_json['licenseKeys']['count']
        license_keys = [item['key'] for item in response_json['licenseKeys']['licenseKey']]

        logging.info(
            f'Maximum Number of Agents: {max_agents}, Agents Left: {agents_left}, License Count: {license_count}. License Keys: {license_keys} ')

        return max_agents, agents_left, license_count, license_keys

    # todo Handle status from API calls & Catch Exceptions
    def removeLicenseFromServer(self, licenseKey):
        header = {'Content-Type': 'text/plain'}
        api_s = f'{self.base_url}server/licensingData/licenseKeys/{licenseKey}'
        logging.info(f'removeLicenseFromServer({licenseKey})')
        r = requests.delete(api_s, headers=header)
        logging.info(f"Removed LicenseKey: {licenseKey} ===> Status: {r.content.decode('utf-8')}  ")

    def addLicenseToServer(self, licenseKey):
        header = {'Content-Type': 'text/plain'}
        api_s = f'{self.base_url}server/licensingData/licenseKeys'
        logging.info(f'addLicenseToServer({licenseKey})')
        r = requests.post(api_s, headers=header, data=f'{licenseKey}')
        logging.info(f"Added LicenseKey: {licenseKey} ===> Status: {r.content.decode('utf-8')}  ")


class TCLMApplication:
    def __init__(self, config_file):
        assert os.path.exists(config_file), f'{config_file} should be present in the home directory'
        self.tc_cfg = TCConfig(config_file)
        self.instance_list = self.tc_cfg.get_tc_list()
        self.licensedb = LicenseDB(self.tc_cfg)

    # todo
    # Remove licenses from agents running idle for more than n days and return them to LMDB
    # if the buffer of licenses is less than the set limit acquire licenses from LMDB and add them
    def process_instance_license(self, tc_instance):
        tci = TCInstance(self.tc_cfg, tc_instance)

        # Revoke Authorization of Agents that are idle
        agents_list = tci.getConnectedAgents()
        logging.info(f'Connected Agents List: {agents_list}')
        for agent_name in agents_list:
            idle4days = tci.getAgentIdleDays(agent_name)
            if idle4days > tci.idle_days:
                tci.revokeAgentAuthorization(agent_name)

        x = self.licensedb.available_licenses_in_db()
        agents_max, agents_left, license_count, license_keys = tci.get_licenseData()

        if agents_left < tci.license_buffer_size:
            logging.info(f'Number of free licenses allocated to instance {tc_instance} is below threshold: {tci.license_buffer_size}, Adding licenses...')
            license_key = self.licensedb.reserve_license(tci.url)
            logging.info(f'Reserved License Key From LMDB: {license_key}')
            tci.addLicenseToServer(license_key)

        if agents_left > tci.license_buffer_size:
            logging.info(f'Number of free licenses allocated to instance {tc_instance} is over threshold: {tci.license_buffer_size}, Removing licenses...')
            license_key = self.licensedb.release_license(tci.url)
            logging.info(f'Released License Key Back to LMDB: {license_key}')
            tci.removeLicenseFromServer(license_key)

        self.licensedb.available_licenses_in_db()
        agents_max, agents_left, license_count, license_keys = tci.get_licenseData()

    def process_licenses_for_all_instances(self):
        for instance in self.instance_list:
            self.process_instance_license(instance)


def set_output_files(instance: str, file_type: str) -> str:
    """
    file_type = [csv|log]
    """
    assert file_type in ['csv', 'log']
    dir_prefix = rf'C:\temp\Teamcity' if platform.system() == "Windows" else '/infrastructure/tclm/log'
    assert os.path.isdir(dir_prefix), f"dir_prefix {dir_prefix} not found"

    prefix = os.path.join(dir_prefix, instance)
    if not os.path.isdir(prefix):
        os.makedirs(prefix)
    assert os.path.isdir(prefix)
    ts = dt.datetime.now()
    out_file = os.path.join(prefix, f"tclm_{instance}_{ts:%Y-%m-%d-%H-%M}.{file_type}")
    return out_file


def process_args():
    def check_default_days(val):
        try:
            ival = int(val)
        except ValueError:
            raise argparse.ArgumentTypeError("%s - Invalid Idle Days, must be an integer greater than zero" % val)
        if ival < 1:
            raise argparse.ArgumentTypeError("%s Idle days must be greater than zero" % val)
        return ival

    parser = argparse.ArgumentParser(
        description=TCLM_VERSION + 'Update retention.days attribute based on the value of retention.pinned')
    parser.add_argument('--instance', "-i", required=True,
                        help='Team City instance nickname - or1, is, ir, ba, ...  Required')
    parser.add_argument('--default_days', "-d", default=5, type=check_default_days, )
    parser.add_argument('--buffersize', "-b", type=int, default=10,
                        help='Size of Buffer of licenses. Default=10')
    parser.add_argument('--apply', "-a", default=False, action="store_true",
                        help='Apply the identified changes. If not specified, runs in dry run mode and produce a '
                             'report. Default is dryrun mode')
    return parser.parse_args()


def driver(args):
    csv_file = set_output_files(args.instance, 'csv')
    log_file = set_output_files(args.instance, 'log')
    logging.basicConfig(filename=log_file, filemode='w',
                        format='%(name)s - %(levelname)s - %(message)s',
                        level=logging.INFO)

    logutil.set_logging(log_file=log_file)
    logging.info(TCLM_VERSION + 'Running with command line args: %s', args)

    tclm_app = TCLMApplication('config.json')
    tclm_app.process_instance_license('dev')


if __name__ == '__main__':
    arg = process_args()
    driver(arg)
