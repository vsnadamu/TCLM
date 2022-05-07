import os
import platform
import json


class TCConfig:

    def __init__(self, config_file='config.json', instance=None):
        self.kr_system = "TCLM"
        if platform.system() == 'Linux':
            from keyrings.cryptfile.cryptfile import CryptFileKeyring
            self.kr = CryptFileKeyring()
            self.kr.keyring_key = self.kr_system
        else:
            import keyring
            self.kr = keyring
        if config_file is None:
            return

        assert os.path.exists(config_file), f"Config file {config_file} not found"
        self.config = json.load(open(config_file))

    def get_generation_date(self):
        gen_date = self.config.get('license_manager_config').get('generation_date')
        return(gen_date)

    def get_tc_list(self):
        instances = [item for item in self.config.get('tc_instances')]
        excluded = self.config.get('tc_instance_exclude_list')
        return [item for item in instances if item not in excluded]

    def get_lmdb_config(self):
        if db := self.config.get('license_manager_config').get('database'):
            db['auth'] = [self.resolve_password(var) for var in db['auth']]
        return dict(
            Driver=db['driver'],
            Server=db['primary_host'],
            Database=db['database'],
            Trusted_connection=db['trusted_connection'],
            uid=db['auth'][0],
            pwd=db['auth'][1]
        )

    def get_tc_config(self, instance):
        config = self.config.get('tc_instances').get(instance)

        if not config:
            raise Exception(f"TC Instance {instance} not defined in config file")
        config['auth'] = [self.resolve_password(var) for var in config['auth']]
        return config



    def get_tcdb_config(self, instance, role='PRIMARY'):
        config = self.config.get('tc_instances').get(instance)

        if not config:
            raise Exception(f"TC Instance {instance} not defined in config file")
        if db := config.get('database'):
            db['auth'] = [self.resolve_password(var) for var in db['auth']]

        return dict(
            Driver=db['driver'],
            Server=db['primary_host'],
            Database=db['database'],
            Trusted_connection=db['trusted_connection'],
            uid=db['auth'][0],
            pwd=db['auth'][1]
        )


    def resolve_password(self, value):
        '''
        Process ENV, KEYRING prefixes
        '''
        if ':' not in value:
            return value
        prefix, var = value.split(':')
        if prefix == 'ENV':
            assert var in os.environ, f"Envioronment variable {var} not defined"
            return os.getenv(var)
        if prefix == 'KEYRING':
            return self.keyring_lookup(var)

        raise Exception(f"Unrecognized scheme {prefix} for var {var}")

    def keyring_setup(self, name, pwd):
        self.kr.set_password(self.kr_system, name, pwd)
        print(f"Setup {name} password in keyring")

    def keyring_lookup(self, name):
        try:
            pwd = self.kr.get_password(self.kr_system, name)
        except Exception as ex:
            raise Exception(f"Failed to get password from keyring for system {self.kr_system} name {name}: {ex}")

        if pwd is None:
            msg = (f"Password not defined in keyring for system {self.kr_system} name {name} - "
                   f"use af_config.keyring_setup('{name}', 'pwd') to define it")
            raise Exception(msg)

        return pwd
