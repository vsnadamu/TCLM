# TCLM
Teamcity License Management - Intial
Distributes the floating licenses among the various instances according to need/demand

For a given instance, 
Checks if any of the agents are idle for a specific period of time specified by 'idle_days' 
attribute in Config.json. Idle agent is the one which has finished its last build.  It is determined by comparing 
the date amd time of its last build with current time.  If the agent is idle for a 'idle_days' then it is 
authorization is revoked.
It then compares total number of Agents authorized (Licensed) against the Number of Licenses installed.  The difference is
the buffer of licenses available.  If this buffer is smaller than the value specified in the config.json (license_buffer_size)
then the program will add more licenses to the instance from the the License Manager Database.  If it is more than that buffer
then it will release the licenses and return them to the Database
