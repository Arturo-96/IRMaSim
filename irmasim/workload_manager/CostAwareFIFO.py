import math
import statistics
from irmasim.workload_manager.WorkloadManager import WorkloadManager
from irmasim.Job import Job
from irmasim.Task import Task
from irmasim.platform.BasicNode import BasicNode
from irmasim.platform.models.modelV1.Node import Node
from irmasim.Options import Options
from typing import TYPE_CHECKING
import importlib

if TYPE_CHECKING:
    from irmasim.Simulator import Simulator

class CostAwareFIFO(WorkloadManager):
    def __init__(self, simulator: 'Simulator'):
        super(CostAwareFIFO, self).__init__(simulator)
        if simulator.platform.config["model"] != "modelV1":
            raise Exception("CostAware workload manager needs a modelV1 platform")
        options = Options().get()

        mod = importlib.import_module("irmasim.platform.models." + options["platform_model_name"] + ".Node")
        klass = getattr(mod, 'Node')
        self.resources = []
        self.resources.extend(self.simulator.get_resources(klass))
        self.idle_resources = len(self.resources)
        self.idle_nodes = []
        self.idle_nodes.extend(self.simulator.get_resources(klass))
        self.busy_nodes = []

        self.pending_jobs = []
        self.delayed_jobs = []
        self.running_jobs = []
        self.costs = simulator.costs
        self.schedule = []

    def on_job_submission(self, jobs: list):
        self.pending_jobs.extend(jobs)
        while self.schedule_next_job():
            pass

    def on_job_completion(self, jobs: list):
        for job in jobs:
            #Not necesary for now
            #for task in job.tasks:
                #self.deallocate(task)
            self.running_jobs.remove(job)
        while self.schedule_next_job():
            pass

    def  on_job_activation(self, jobs:  list):
        for job in jobs:
            self.schedule_delayed_job(job)

    def schedule_delayed_job(self, job):
        nodes = []
        for plannedJob in self.schedule:
            if job.id == plannedJob[3].id:
                nodes = plannedJob[2]
        self.allocate(job,nodes)
        self.simulator.schedule(job.tasks)
        self.running_jobs.append(job)

    def schedule_next_job(self):
        if self.pending_jobs != []:
            next_job = self.pending_jobs.pop(0)

            if  next_job.slack:
                #move down to global minimun within slack
                timestep = list(self.costs.keys())[1]
                slice = next_job.submit_time
                slices = 0
                currentSlice = math.floor(slice/timestep)*timestep
                while currentSlice < slice + next_job.req_time:
                    slices += 1
                    currentSlice += timestep
                price = 0
                for step in range(slices):
                    price += self.costs[math.floor((slice + step*timestep)/timestep)*timestep]*next_job.req_energy/slices
                prev_price = math.inf
                delay = 0
                nodes = []
                while slice + next_job.req_time < next_job.slack:
                    slices = 0
                    currentSlice = math.floor(slice/timestep)*timestep
                    while currentSlice < slice + next_job.req_time:
                        slices += 1
                        currentSlice += timestep
                    price = 0
                    for step in range(slices):
                        price += self.costs[math.floor((slice + step*timestep)/timestep)*timestep]*next_job.req_energy/slices
                    if price < prev_price:
                        time = slice
                        #search slot within time slice
                        while time <= slice + timestep:
                            #check if time window is free
                            freeResources = []
                            for resource in self.resources:
                                freeResources.append([resource, resource.count_cores()])
                            nextTime= math.inf
                            for plannedJob in self.schedule:
                                #overlap in schedule
                                if plannedJob[0] < time + next_job.req_time and time < plannedJob[1]:
                                    looplist = freeResources.copy()
                                    for resource in freeResources:
                                        if resource[0] in plannedJob[2]:
                                            resource[1] -= len(plannedJob[3].tasks)
                                        if resource[1] <= 0:
                                            looplist.remove(resource)
                                    freeResources = looplist

                                    #find soonest end of overlaping schedules
                                    if plannedJob[1] < nextTime:
                                        nextTime = plannedJob[1]
                            
                            cores = 0
                            freeNodes = []
                            #Take necesary nodes
                            for resource in freeResources:
                                freeNodes.append(resource[0])
                                cores += resource[1]
                                if cores >= len(next_job.tasks):
                                    break
                            
                            if freeNodes and cores >= len(next_job.tasks):
                                nodes = freeNodes.copy()
                                prev_price = price
                                delay = time
                                break
                            else:
                                time = nextTime + 1
                    #advance to next time slice
                    slice = math.floor(slice/timestep)*timestep + timestep
                #mark execution time as ocupied
                self.schedule.append([delay, delay + next_job.req_time, nodes, next_job])
                
                self.simulator.delay(next_job,delay)
                self.delayed_jobs.append(next_job)

            else:
                freeResources = []
                for resource in self.resources:
                    freeResources.append([resource, resource.count_cores()])

                for plannedJob in self.schedule:
                    #overlap in schedule
                    if plannedJob[0] < self.simulator.simulation_time + next_job.req_time and self.simulator.simulation_time < plannedJob[1]:
                        looplist = freeResources.copy()
                        for resource in freeResources:
                            if resource[0] in plannedJob[2]:
                                resource[1] -= len(plannedJob[3].tasks)
                            if resource[1] <= 0:
                                looplist.remove(resource)
                            freeResources = looplist

                cores = 0
                nodes = []
                #Take necesary nodes
                for resource in freeResources:
                    nodes.append(resource[0])
                    cores += resource[1]
                    if cores >= len(next_job.tasks):
                        break

                if nodes:
                    self.schedule.append([self.simulator.simulation_time, self.simulator.simulation_time + next_job.req_time, nodes, next_job])
                    self.allocate(next_job, nodes)
                    self.simulator.schedule(next_job.tasks)
                    self.running_jobs.append(next_job)
                    return True
            
                else:
                    return False

        else:
            return False

    def on_end_step(self):
        pass

    def on_end_simulation(self):
        pass

    def set_costs(self, costs: dict):
        self.costs = costs

    def allocate(self, job: Job, nodes: list):
        cores = []
        for node in nodes:
            cores.extend(node.idle_cores().copy())
        for task in job.tasks:
            task.allocate(cores.pop(0).full_id())

    #Not used for now
    def deallocate(self, task: Task):
        for resource in range(len(self.resources)):
           if self.resources[resource][1] == 0 and self.resources[resource][0] == task.resource:
               self.resources[resource][1] = 1
               self.idle_resources += 1
               break
           