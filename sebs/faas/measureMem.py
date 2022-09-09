import subprocess
import threading
from threading import Thread
import time


class MeasureMem(Thread):

    def __init__(self, containerId: str):
        """
        args:
            containerId (string): Long container id of the docker container
        """
        Thread.__init__(self)
        self.mem = []
        self.running = threading.Event()
        self.running.set()
        self.containerId = containerId

    def run(self):
        """
        Read memory.current cgroups file while container is running.
        """
        while self.running.is_set():
            longId = "docker-" + self.containerId + ".scope"
            try:
                cmd = "cat /sys/fs/cgroup/system.slice/{id:}/memory.current".format(id = longId)
                p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, shell=True)
                self.mem.append(int(p.communicate()[0].decode()))
            except:
                cmd = "cat /sys/fs/cgroup/memory/system.slice/{id:}/memory.current".format(id = longId)
                p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, shell=True)
                self.mem.append(int(p.communicate()[0].decode()))
            time.sleep(0.1)
