
import json
import logging
import os


# https://stackoverflow.com/questions/3232943/update-value-of-a-nested-dictionary-of-varying-depth
import collections.abc

def update(d, u):
    for k, v in u.items():
        if isinstance(v, collections.abc.Mapping):
            d[k] = update(d.get(k, {}), v)
        else:
            d[k] = v
    return d


class cache:

    cache_dir = None
    cached_config = {}
    '''
        Indicate that cloud offerings updated credentials or settings.
        Thus we have to write down changes.
    '''
    config_updated = False

    def __init__(self, cache_dir):
        self.cache_dir = os.path.abspath(cache_dir)
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir, exist_ok=True)
        else:
            self.load_config()

    def load_config(self):
        for cloud in ['azure', 'aws']:
            cloud_config_file = os.path.join(self.cache_dir, '{}.json'.format(cloud))
            if os.path.exists(cloud_config_file):
                self.cached_config[cloud] = json.load(open(cloud_config_file, 'r'))
    
    def get_config(self, cloud):
        return self.cached_config[cloud] if cloud in self.cached_config else None

    '''
        Update config values. Sets flag to save updated content in the end.
        val: new value to store
        keys: array of consecutive keys for multi-level dictionary
    '''
    def update_config(self, val, keys):
        def map_keys(obj, val, keys):
            if len(keys):
                return { keys[0]: map_keys(obj, val, keys[1:]) }
            else:
                return val
        update(self.cached_config, map_keys(self.cached_config, val, keys))
        self.config_updated = True

    def shutdown(self):
        if self.config_updated:
            print(self.cached_config)
            for cloud in ['azure', 'aws']:
                if cloud in self.cached_config:
                    cloud_config_file = os.path.join(
                            self.cache_dir, '{}.json'.format(cloud)
                        )
                    logging.info('Update cached config {}'.format(cloud_config_file))
                    with open(cloud_config_file, 'w') as out:
                        json.dump(self.cached_config[cloud], out, indent=2)
