import yaml
import sys
import argparse

def create_yaml_config(max_users, frequency, cycles):
    config = {
        'config': {
            'target': 'http://172.17.0.2:9000',
            'phases': []
        },
        'scenarios': [
            {
                'flow': [
                    {
                        'post': {
                            'url': '/post',
                            'json': '{{ payload }}'
                        }
                    }
                ]
            }
        ],
        'payload': '{{ $processEnvironment.PAYLOAD_FILE }}'
    }

    for i in range(cycles):
        config['config']['phases'].extend([
            {
                'duration': frequency,
                'arrivalRate': 1 if i == 0 else 5,
                'rampTo': max_users,
                'name': f'Ramp-up phase {i+1}'
            },
            {
                'duration': frequency,
                'arrivalRate': max_users,
                'rampTo': 5,
                'name': f'Ramp down phase {i+1}'
            }
        ])

    # Remove the last ramp down phase
    config['config']['phases'].pop()

    return config

def main():
    parser = argparse.ArgumentParser(description='Generate YAML config for load testing')
    parser.add_argument('max_users', type=int, help='Maximum number of users')
    parser.add_argument('frequency', type=int, help='Duration of each phase in seconds')
    parser.add_argument('cycles', type=int, help='Number of cycles')
    
    args = parser.parse_args()

    config = create_yaml_config(args.max_users, args.frequency, args.cycles)

    with open('load_test_config.yaml', 'w') as f:
        yaml.dump(config, f, default_flow_style=False)

    print("YAML configuration file 'load_test_config.yaml' has been created.")

if __name__ == '__main__':
    main()