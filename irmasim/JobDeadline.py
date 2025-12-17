import math
from irmasim.Task import Task
from irmasim.Job import Job


class Job(Job):
    def __init__(self, id: int, name: str, submit_time: float, nodes: int, ntasks: int, ntasks_per_node: int, req_ops : int, ipc : float, req_time : float, req_energy : int, mem : int, mem_vol : float, deadline: float):
        self.deadline  = deadline
        Job.__init__(self, id, name, submit_time, nodes, ntasks, ntasks_per_node, req_ops, ipc, req_time, req_energy, mem, mem_vol)
    
    @classmethod
    def header(klass):
        return "id,req_time,ntasks,mem,submit_time,start_time,finish_time,execution_time,operations,mem_vol,profile,resources,deadline"
