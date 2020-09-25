#test
config = {
    "output_size": 100
}
result = {}
#import
import uuid
#function
def fill_dict(dict_to_fill, number_of_entries):
    for i in range(number_of_entries):
        dict_to_fill[str(uuid.uuid1())] = str(uuid.uuid1())
        
#run
number_of_entries = config.get("output_size")
fill_dict(result, number_of_entries)
print(result)