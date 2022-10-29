from pypapi import papi_high
from pypapi import events as events
from pypapi import papi_low as papi

from datetime import datetime, timedelta

import random
import numpy as np

papi.library_init()

evs = papi.create_eventset()
papi.add_event(evs, events.PAPI_TOT_INS)
papi.add_event(evs, events.PAPI_TOT_CYC)
papi.add_event(evs, events.PAPI_BR_INS)
papi.add_event(evs, events.PAPI_BR_MSP)

data = []

def test(x):
    j = 0
    for i in range(0, x):
        j += random.randint(0, 1)

with_papi = True
with_overflow = True

times = []
test_samples = 10
cur_time = datetime.now().timestamp()
for i in range(0, test_samples):
    if with_overflow:
        # Low buffer size to test double buffering
        papi.overflow_sampling(evs, events.PAPI_TOT_INS, 1000000, 100)
    if with_papi:
        papi.start(evs)
    start = datetime.now()
    test(20000)
    end = datetime.now()
    times.append((end - start) / timedelta(microseconds=1) / 1000.0)
    if with_papi:
        papi.stop(evs)
print('Min %f Mean %f Std %f' % (np.min(times), np.mean(times), np.std(times)))

data = papi.overflow_sampling_results(evs)
print('Start time: {}'.format(cur_time))
print('First data: {}'.format(data[0][0:4]))

papi.cleanup_eventset(evs)
papi.destroy_eventset(evs)
