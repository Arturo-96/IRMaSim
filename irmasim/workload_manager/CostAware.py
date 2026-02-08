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
        if self.pending_jobs != [] and self.idle_resources >= len(self.pending_jobs[0].tasks):

            #W - knapsack size = nodes  available
            W = self.idle_resources

            #val - jobs power consumption
            val = []

            #wt - number of nodes required by jobs
            wt = []

            #calculate if peak or off-peak
            peak = True
            median = statistics.median(self.costs.values())
            timestep = list(self.costs.keys())[1]
            currentSlice = math.floor(self.simulator.simulation_time/timestep)*timestep
            if self.costs[currentSlice] < median:
                peak = False

            for job in self.pending_jobs:
                if peak:
                    val.append(job.req_energy)
                else:
                    val.append(-job.req_energy)
                wt.append(job.nodes)
            
            next_job = self.pending_jobs.pop(self.knapsack(W, val, wt))

            for task in next_job.tasks:
                    self.allocate(task)
            self.simulator.schedule(next_job.tasks)
            self.running_jobs.append(next_job)

        else:
            return False

    #returns maximun value that can be put on the knapsack
    def knapsackRec(self, W, val, wt, n, memo):

        # Base Case
        if n == 0 or W == 0:
            return 0

        # Check if we have previously calculated the same subproblem
        if memo[n][W] != -1:
            return memo[n][W]

        pick = 0

        #pick item if knapsack capacity is not exceeded
        if wt[n - 1] <= W:
            pick = val[n - 1] + self.knapsackRec(W - wt[n - 1], val, wt, n - 1, memo)

        #item not picked
        notPick = self.knapsackRec(W, val, wt, n - 1, memo)

        # Store the result in memo[n][W] and return it
        memo[n][W] = max(pick, notPick)
        return memo[n][W]    
    
    #W - knapsack size = nodes  available
    #val - jobs power consumption
    #wt - number of nodes required by jobs
    def knapsack(self, W, val, wt):
        n = len(val)

        # Memoization table to store the results
        memo = [[-1] * (W + 1) for _ in range(n + 1)]

        return self.knapsackRec(W, val, wt, n, memo)

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