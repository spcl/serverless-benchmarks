#test
config = {
    "duration": 100
}
number = 0
result = {}
#import
from time import sleep
#function

#run
sleep_time = config.get('duration')
sleep(sleep_time)
result[str(number)] = { 'sleep_time': sleep_time }