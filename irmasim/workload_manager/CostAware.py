import math
import statistics
from irmasim.workload_manager.WorkloadManager import WorkloadManager
from irmasim.Job import Job
from irmasim.Task import Task
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from irmasim.Simulator import Simulator

class CostAware(WorkloadManager):
    def __init__(self, simulator: 'Simulator'):
        super(CostAware, self).__init__(simulator)
        if simulator.platform.config["model"] != "modelV1":
            raise Exception("Minimal workload manager needs a modelV1 platform")
        self.resources = [ [ resource_id, 1 ] for resource_id in self.simulator.get_resources_ids() ]
        self.idle_resources = len(self.resources)
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
            for task in job.tasks:
                self.deallocate(task)
            self.running_jobs.remove(job)
        while self.schedule_next_job():
            pass

    def  on_job_activation(self, jobs:  list):
        for job in jobs:
            self.schedule_delayed_job(job)

    def schedule_delayed_job(self, job):
        if self.idle_resources >= len(job.tasks):
            for task in job.tasks:
                self.allocate(task)
            self.simulator.schedule(job.tasks)
            self.running_jobs.append(job)

    def schedule_next_job(self):
        if self.pending_jobs != []:
            next_job = self.pending_jobs.pop(0)

            if  next_job.slack:
                #move down to global minimun within slack
                timestep = list(self.costs.keys())[1]
                slice = next_job.submit_time
                prev_price = self.costs[math.floor(slice/timestep)*timestep]
                price = self.costs[math.floor(slice/timestep)*timestep]
                delay = 0
                while slice + next_job.req_time < next_job.slack:
                    price = self.costs[math.floor(slice/timestep)*timestep]
                    if price < prev_price:
                        time = slice
                        #search slot within time slice
                        while time < slice + timestep:
                            #check if time window is free
                            freeResources = len(self.resources)
                            nextTime= math.inf
                            for slot in self.schedule:
                                #overlap in schedule
                                if slot[0] < time + next_job.req_time and time < slot[1]:
                                    freeResources -= slot[2]
                                    #find soonest end of overlaping schedules
                                    if slot[1] < nextTime:
                                        nextTime = slot[1]
                            if freeResources >= len(next_job.tasks):
                                prev_price=price
                                delay = time
                                break
                            else:
                                time = nextTime + 1
                    #advance to next time slice
                    slice = math.floor(slice/timestep)*timestep + timestep
                #mark execution time as ocupied
                self.schedule.append([delay, delay + next_job.req_time, len(next_job.tasks)])
                
                self.simulator.delay(next_job,delay)
                self.delayed_jobs.append(next_job)

            elif self.idle_resources >= len(next_job.tasks):
                #TODO: comprobar si tengo recursos para el instante actual?
                for task in next_job.tasks:
                    self.allocate(task)
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

    def allocate(self, task: Task):
        resource = 0
        while self.resources[resource][1] == 0:
            resource += 1
        self.resources[resource][1] = 0
        self.idle_resources -= 1
        task.allocate(self.resources[resource][0])

    def deallocate(self, task: Task):
        for resource in range(len(self.resources)):
           if self.resources[resource][1] == 0 and self.resources[resource][0] == task.resource:
               self.resources[resource][1] = 1
               self.idle_resources += 1
               break