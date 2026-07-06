from irmasim.workload_manager.WorkloadManager import WorkloadManager
from irmasim.Job import Job
from irmasim.Options import Options
from irmasim.Task import Task
import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from irmasim.Simulator import Simulator

class Minimal(WorkloadManager):
    def __init__(self, simulator: 'Simulator'):
        super(Minimal, self).__init__(simulator)
        if simulator.platform.config["model"] != "modelV1":
            raise Exception("Minimal workload manager needs a modelV1 platform")
        options = Options().get()
        
        mod = importlib.import_module("irmasim.platform.models." + options["platform_model_name"] + ".Node")
        klass = getattr(mod, 'Node')
        self.resources = [ [ resource_id, 1 ] for resource_id in self.simulator.get_resources_ids() ]
        self.resourcesOpt = self.simulator.get_resources(klass)
        self.idle_resources = len(self.resources)
        self.pending_jobs = []
        self.running_jobs = []

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

    def schedule_next_job(self):
        if self.pending_jobs != [] and self.idle_resources >= len(self.pending_jobs[0].tasks):
            next_job = self.pending_jobs.pop(0)
            for task in next_job.tasks:
                self.allocate(task)
            self.simulator.schedule(next_job.tasks)
            self.running_jobs.append(next_job)
            return True
        else:
            return False
        
    def schedule_jobs_solver(self, time: int, jobs: list, schedule: list):
        nextTime = time + jobs[0].req_time
        newSchedule = []
        for job in jobs:
            planned = False
            while not planned:
                freeResources = sum(resource.count_cores() for resource in self.resourcesOpt)
                for plannedJob in schedule:
                    #ignore unplanned jobs
                    if plannedJob[0] < 0:
                        continue
                    #overlap in schedule
                    if plannedJob[0] < time + job.req_time and time < plannedJob[0] + plannedJob[1].req_time:
                        if plannedJob[0] + plannedJob[1].req_time > nextTime:
                            nextTime = plannedJob[0] + plannedJob[1].req_time
                        #remove used resources
                        freeResources -= len(plannedJob[1].tasks)
            
                #check if enough free resources
                if freeResources >= len(job.tasks):
                    #schedule
                    schedule.append([time,job])
                    newSchedule.append([time,job])
                    planned = True
                else:
                    #jump to end of previous job
                    time = nextTime
            
        return newSchedule

    def on_end_step(self):
        pass

    def on_end_simulation(self):
        pass

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

