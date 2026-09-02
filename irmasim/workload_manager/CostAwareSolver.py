import math
import statistics
from irmasim.workload_manager.WorkloadManager import WorkloadManager
from irmasim.Job import Job
from irmasim.Task import Task
from irmasim.platform.BasicNode import BasicNode
from irmasim.platform.models.modelV1.Node import Node
from irmasim.Options import Options
from typing import TYPE_CHECKING
from itertools import groupby
import importlib
import logging
from ortools.sat.python import cp_model

if TYPE_CHECKING:
    from irmasim.Simulator import Simulator

class CostAwareSolver(WorkloadManager):
    def __init__(self, simulator: 'Simulator'):
        super(CostAwareSolver, self).__init__(simulator)
        if simulator.platform.config["model"] != "modelV1":
            raise Exception("CostAware workload manager needs a modelV1 platform")
        options = Options().get()

        self.logger = logging.getLogger(__name__)
        handler=logging.FileHandler("results.log", mode="w")
        self.logger.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(message)s"))
        self.logger.addHandler(handler)
        self.logger.propagate = False

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
        self.secondary = None
        self.schedule = []
        self.static_jobs = []
        self.inmediate_jobs = []

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

            for plannedJob in self.static_jobs:
                if plannedJob[1].id == job.id:
                    print(f"JOB REMOVED: {job.id} at {self.simulator.simulation_time}")
                    self.static_jobs.remove(plannedJob)
                    break
        while self.schedule_next_job():
            pass

    def  on_job_activation(self, jobs:  list):
        for job in jobs:
            self.schedule_delayed_job(job)

    def schedule_delayed_job(self, job):
        for plannedJob in self.schedule:
            if job.id == plannedJob[1].id:
                self.static_jobs.append(plannedJob)
                self.schedule.remove(plannedJob)
                break
        
        self.allocate(job)
        print("Allocating")
        print(f"job {job.id} tasks to allocate: {len(job.tasks)} available cores: {sum(len(n.idle_cores()) for n in self.resources)} at {self.simulator.simulation_time}")
        self.simulator.schedule(job.tasks)
        self.running_jobs.append(job)
        

    def schedule_next_job(self):
        if self.pending_jobs != []:
            print("===SOLVER===")
            print(f"starting at {self.simulator.simulation_time}")
            print(f"double checking {self.pending_jobs[0].submit_time}")

            print("--- STATE ---")
            print("schedule:")
            for job in self.schedule:
                print(f"Job: {job[1].id} start time: {job[0]}")
                print(f"    cores used: {len(job[1].tasks)}")

            print("\nstatic:")
            for job in self.static_jobs:
                print(f"Job: {job[1].id} start time: {job[0]}")
                print(f"    cores used: {len(job[1].tasks)}")


            for job in self.pending_jobs:
                if job.slack and job.slack > 0:
                    self.schedule.append([-1, job])
                else:
                    self.inmediate_jobs.append(job)

            self.pending_jobs = []
            
            print("JOBS:")
            for job in self.schedule:
                print("Job: "+str(job[1].id)+" slack: "+str(job[1].slack))

            #compact static jobs for solver
            compactedJobs = self.compact_jobs(self.static_jobs)
            
            self.solve(compactedJobs, self.simulator.simulation_time)

            if self.inmediate_jobs:
                print("INMEDIATES")
                for job in self.inmediate_jobs:
                    print("Job: "+str(job.id)+" slack: "+str(job.slack))

                newSchedule = self.secondary.schedule_jobs_solver(self.simulator.simulation_time, self.inmediate_jobs, self.schedule.copy() + self.static_jobs.copy())
                for job in newSchedule:
                    self.static_jobs.append(job)

                self.inmediate_jobs = []

            self.logger.info("New solution")

            print("Para el logger static")
            if self.static_jobs:
                for job in self.static_jobs:
                    print(f"metiendo al log job {job[1].id}")
                    self.logger.info(f"{job[1].id},{job[0]},{job[1].req_time},{len(job[1].tasks)}")
            
            print("Para el logger schedule")
            for job in self.schedule:
                print(f"metiendo al log job {job[1].id}")
                self.logger.info(f"{job[1].id},{job[0]},{job[1].req_time},{len(job[1].tasks)}")

            print("\n---Estaticos---")
            for job in self.static_jobs:
                print(f"  Job {job[1].id}: req_time={job[1].req_time}, initTime={job[0]}")

            print("---ALLOCATION---")
            #Schedule inmediate jobs
            print(f"static {len(self.static_jobs)}")
            for job in self.static_jobs:
                if job[0] >= self.simulator.simulation_time:
                    print(f"job: {job[1].id} tasks: {len(job[1].tasks)}")
                    self.simulator.delay(job[1],job[0])
                    if job[1] not in self.delayed_jobs:
                        self.delayed_jobs.append(job[1])

            #Delay all jobs
            print(f"delaying {len(self.schedule)} jobs")
            for job in self.schedule:
                print("JOB: "+str(job[1].id))
                print(f"cores used: {len(job[1].tasks)}")
                print("Init Time: "+str(job[0]))
                self.simulator.delay(job[1],job[0])
                if job[1] not in self.delayed_jobs:
                    self.delayed_jobs.append(job[1])


        else:
            return False
        
    def solve(self,  compactedJobs: list, currentTime: int):
        print("Starting Solver")
        timestep = list(self.costs.keys())[1]
        T_max = list(self.costs.keys())[-1] + timestep
        M = T_max + sum(job[1].req_time for job in self.schedule) + 1
            
        #define model
        model = cp_model.CpModel()

        #problem variables
        slicesSingle = {}
        slicesIniOnly = {}
        slicesInter = {}
        slicesEndOnly = {}
        slicesOff = {}
        delta = {}
        initTime = {}
        interval = {}

        for plannedJob in self.schedule:
            initTime[plannedJob[1].id] = model.NewIntVar(int(currentTime), plannedJob[1].slack, f'iniTime_{plannedJob[1].id}') #initTime
            interval[plannedJob[1].id] = model.NewFixedSizeIntervalVar(initTime[plannedJob[1].id], plannedJob[1].req_time, f"interval_{plannedJob[1].id}")

            slicesSingle[plannedJob[1].id] = {}
            slicesIniOnly[plannedJob[1].id] = {}
            slicesInter[plannedJob[1].id] = {}
            slicesEndOnly[plannedJob[1].id] = {}
            slicesOff[plannedJob[1].id] = {}
            delta[plannedJob[1].id] = {}

            for timeSlice in self.costs.keys():
                slicesSingle[plannedJob[1].id][timeSlice] = model.NewBoolVar(f'sliceSingle_{plannedJob[1].id}_{timeSlice}') #slices true if initial and final are the same
                slicesIniOnly[plannedJob[1].id][timeSlice] = model.NewBoolVar(f'sliceIniOnly_{plannedJob[1].id}_{timeSlice}') #slices only the initial one is true
                slicesInter[plannedJob[1].id][timeSlice] = model.NewBoolVar(f'intermediate_slice_{plannedJob[1].id}_{timeSlice}') #slices the ones between initial and final are true
                slicesEndOnly[plannedJob[1].id][timeSlice] = model.NewBoolVar(f'sliceEndOnly_{plannedJob[1].id}_{timeSlice}') #slices only the final one is true (can be the same as initial)
                slicesOff[plannedJob[1].id][timeSlice] = model.NewBoolVar(f'inactive_slice_{plannedJob[1].id}_{timeSlice}') #slices true if job doesn't execute in it
                delta[plannedJob[1].id][timeSlice] = model.NewIntVar(0, timestep, f'deltaTime_{timeSlice}_{plannedJob[1].id}') #Time the job spends in each slice

        #function to minimize
        objective_terms = []
        for plannedJob in self.schedule:
            power = plannedJob[1].req_energy / plannedJob[1].req_time
            for timeSlice in self.costs.keys():
                objective_terms.append(power * self.costs[timeSlice] * delta[plannedJob[1].id][timeSlice])
        model.Minimize(sum(objective_terms))


        #restrictions

        for plannedJob in self.schedule:
            model.Add(initTime[plannedJob[1].id] + plannedJob[1].req_time <= plannedJob[1].slack) #we respect slacks
            model.Add(sum(slicesIniOnly[plannedJob[1].id].values()) + sum(slicesSingle[plannedJob[1].id].values()) == 1) #Only one initial slice per job
            model.Add(sum(slicesEndOnly[plannedJob[1].id].values()) + sum(slicesSingle[plannedJob[1].id].values()) == 1) #Only one final slice per job
            model.Add(sum(delta[plannedJob[1].id].values()) == plannedJob[1].req_time) #All time per slices adds to required time for execution

            for timeSlice in self.costs.keys():
                #Job can only take one case
                model.Add(
                    slicesOff[plannedJob[1].id][timeSlice] +
                    slicesInter[plannedJob[1].id][timeSlice] +
                    slicesSingle[plannedJob[1].id][timeSlice] +
                    slicesIniOnly[plannedJob[1].id][timeSlice] +
                    slicesEndOnly[plannedJob[1].id][timeSlice] == 1
                )

                # initTime is inside its initial slice
                model.Add(initTime[plannedJob[1].id] - timeSlice >= 0).OnlyEnforceIf(slicesIniOnly[plannedJob[1].id][timeSlice])
                model.Add(initTime[plannedJob[1].id] - timeSlice >= 0).OnlyEnforceIf(slicesSingle[plannedJob[1].id][timeSlice])
                model.Add(timeSlice + timestep - initTime[plannedJob[1].id] >= 0).OnlyEnforceIf(slicesIniOnly[plannedJob[1].id][timeSlice])
                model.Add(timeSlice + timestep - initTime[plannedJob[1].id] >= 0).OnlyEnforceIf(slicesSingle[plannedJob[1].id][timeSlice])

                # end time is inside final slice
                model.Add(initTime[plannedJob[1].id] + plannedJob[1].req_time - timeSlice >= 0).OnlyEnforceIf(slicesEndOnly[plannedJob[1].id][timeSlice])
                model.Add(initTime[plannedJob[1].id] + plannedJob[1].req_time - timeSlice >= 0).OnlyEnforceIf(slicesSingle[plannedJob[1].id][timeSlice])
                model.Add(timeSlice + timestep - initTime[plannedJob[1].id] - plannedJob[1].req_time >= 0).OnlyEnforceIf(slicesEndOnly[plannedJob[1].id][timeSlice])
                model.Add(timeSlice + timestep - initTime[plannedJob[1].id] - plannedJob[1].req_time >= 0).OnlyEnforceIf(slicesSingle[plannedJob[1].id][timeSlice])

                #Delta time is in single slice (delta = req_time)
                model.Add(delta[plannedJob[1].id][timeSlice] == plannedJob[1].req_time).OnlyEnforceIf(slicesSingle[plannedJob[1].id][timeSlice])

                #Delta time in initial slice (delta = end of step - initTime)
                model.Add(delta[plannedJob[1].id][timeSlice] == timeSlice + timestep - initTime[plannedJob[1].id]).OnlyEnforceIf(slicesIniOnly[plannedJob[1].id][timeSlice])

                #Delta time in intermediate slice (delta = timestep)
                model.Add(delta[plannedJob[1].id][timeSlice] == timestep).OnlyEnforceIf(slicesInter[plannedJob[1].id][timeSlice])

                #Delta time in final slice (delta = initTime + reqTime - key)
                model.Add(delta[plannedJob[1].id][timeSlice] == initTime[plannedJob[1].id] + plannedJob[1].req_time - timeSlice).OnlyEnforceIf(slicesEndOnly[plannedJob[1].id][timeSlice])

                #Delta time in inactive slice (delta = 0)
                model.Add(delta[plannedJob[1].id][timeSlice] == 0).OnlyEnforceIf(slicesOff[plannedJob[1].id][timeSlice])

            #slices are in correct order
            model.Add(sum(slicesIniOnly[plannedJob[1].id][timeSlice]*timeSlice for timeSlice in self.costs.keys()) <= sum(slicesEndOnly[plannedJob[1].id][timeSlice]*timeSlice for timeSlice in self.costs.keys())) #init before end
            model.Add(sum(slicesIniOnly[plannedJob[1].id][timeSlice]*timeSlice for timeSlice in self.costs.keys()) <= sum(slicesInter[plannedJob[1].id][timeSlice]*timeSlice for timeSlice in self.costs.keys())) #init before intermediate
            model.Add(sum(slicesInter[plannedJob[1].id][timeSlice]*timeSlice for timeSlice in self.costs.keys()) <= sum(slicesEndOnly[plannedJob[1].id][timeSlice]*timeSlice for timeSlice in self.costs.keys())) #inter before end

        #Overlaps between jobs    
        demands = [len(plannedJob[1].tasks) for plannedJob in self.schedule] #jobs to schedule
        capacity = sum(n.count_cores() for n in self.resources) #available resources

        #Define intervals and demands for static jobs
        static_intervals = []
        for job in compactedJobs:
            demands.append(len(self.get_tasks(job[1])))
            static_intervals.append(model.NewFixedSizeIntervalVar(job[0], job[2] - job[0], f"interval_{plannedJob[1].id}"))

        
        model.AddCumulative(list(interval.values()) + static_intervals, demands, capacity)

        #Define solver from model
        solver = cp_model.CpSolver()

        solver.parameters.max_time_in_seconds = 15.0   
        solver.parameters.num_search_workers = 0        #use al cores    
        solver.parameters.log_search_progress = True
            
        #Solve
        print()
        print("---SOLVING---")
        print()
        result = solver.Solve(model)

        print("solved")


        if  result == cp_model.OPTIMAL:
            print("optimal solution")
        elif result == cp_model.FEASIBLE:
            print("suboptimal solution")
        elif result == cp_model.INFEASIBLE:
            print("INFEASIBLE — problem doesn't have solution")
            print(f"problem had {len(self.schedule)} jobs")
            # Turn a job into inmediate
            self.inmediate_jobs.append(self.schedule.pop(0)[1])
            self.solve(compactedJobs,currentTime)
            return
        elif result == cp_model.NOT_SOLVED:
            print("NOT_SOLVED — couldn't find solution to problem")
            print(f"problem had {len(self.schedule)} jobs")
            # Turn a job into inmediate
            # Turn a job into inmediate
            self.inmediate_jobs.append(self.schedule.pop(0)[1])
            self.solve(compactedJobs,currentTime)
            return
        else:
            print("ERROR")
            print(result)
            print(f"Exporting model with {len(self.schedule)} jobs")
            with open("test.lp", "w") as out_f:
                lp_text = solver.ExportModelAsLpFormat(obfuscate=False)
                out_f.write(lp_text)

        """
        print("--OVERLAPS--")
        for plannedJob in self.schedule:
            for job2 in self.schedule:
                print(f"job {plannedJob[1].id} starts at {initTime[plannedJob[1].id].solution_value()} ends at {initTime[plannedJob[1].id].solution_value() + plannedJob[1].req_time}")
                print(f"job {job2[1].id} starts at {initTime[job2[1].id].solution_value()} ends at {initTime[job2[1].id].solution_value() + job2[1].req_time}")
                print(f"Overlap: {overlap[plannedJob[1].id][job2[1].id].solution_value()}")
            print(f"For job {plannedJob[1].id} overlaping tasks: {sum(len(job2[1].tasks)*overlap[plannedJob[1].id][job2[1].id].solution_value() for job2 in self.schedule)} total cores: {sum(n.count_cores() for n in self.resources)}")
        """
        newSchedule = []

        for job in self.schedule:
 
            newSchedule.append([solver.Value(initTime[job[1].id]), job[1]])
            
        self.schedule = newSchedule

    def get_tasks(self, job):
        if isinstance(job, int):
            return job
        else:
            return len(job.tasks)
        
    def get_id(self, job):
        if isinstance(job[1], int):
            return f'static_{job[0]}'
        else:
            return job[1].id
        
    def compact_jobs(self, jobs: list):
        events = []
        for job in jobs:
            events.append([job[0], len(job[1].tasks)])
            events.append([job[0] + job[1].req_time, -len(job[1].tasks)])
            
        events.sort(key=lambda e:e[0])

        compactedJobs = []
        activeTasks = 0
        prevTime = None

        for time, group in groupby(events, key=lambda e: e[0]):
            if prevTime is not None and activeTasks >= 0:
                compactedJobs.append([prevTime, activeTasks, time])
            for _, tasks in group:
                activeTasks += tasks
            prevTime = time
        return compactedJobs

    def on_end_step(self):
        pass

    def on_end_simulation(self):
        pass

    def set_costs(self, costs: dict):
        self.costs = costs

    def set_secondary(self, manager: WorkloadManager):
        self.secondary = manager

    def allocate(self, job: Job):
        tasks = job.tasks.copy()
        for n in self.resources:
            for core in n.idle_cores():
                if len(tasks) == 0:
                    return
                task = tasks.pop(0)
                task.allocate(core.full_id())
                

    #Not used for now
    def deallocate(self, task: Task):
        for resource in range(len(self.resources)):
           if self.resources[resource][1] == 0 and self.resources[resource][0] == task.resource:
               self.resources[resource][1] = 1
               self.idle_resources += 1
               break