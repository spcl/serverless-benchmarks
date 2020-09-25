#test
result = {}
number = 0
#import
import speedtest
#function
def test_network():
    s = speedtest.Speedtest()
    return {"upload": s.upload(),
        "download": s.download()}
#run
result[str(number)] = test_network()
print(result)
