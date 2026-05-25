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
from ortools.linear_solver import pywraplp

if TYPE_CHECKING:
    from irmasim.Simulator import Simulator

class CostAwareSolver(WorkloadManager):
    def __init__(self, simulator: 'Simulator'):
        super(CostAwareSolver, self).__init__(simulator)
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
        self.secondary = None
        self.schedule = []
        self.static_jobs = []

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
        print(f"tasks to allocate: {len(job.tasks)} available cores: {sum(len(n.idle_cores()) for n in self.resources)}")
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

            #TODO: remove nodes from the job struct
            inmediateJobs = []
            for job in self.pending_jobs:
                if job.slack and job.slack > 0:
                    self.schedule.append([-1, job])
                else:
                    inmediateJobs.append(job)

            self.pending_jobs = []
            
            print("JOBS:")
            for job in self.schedule:
                print("Job: "+str(job[1].id)+" slack: "+str(job[1].slack))

            if inmediateJobs:
                print("INMEDIATES")
                for job in inmediateJobs:
                    print("Job: "+str(job.id)+" slack: "+str(job.slack))

                #TODO: Anhadir abortar si se pasa de slack y testear mas
                newSchedule = self.secondary.schedule_jobs(inmediateJobs[0].submit_time, inmediateJobs, self.schedule.copy() + self.static_jobs.copy())
                for job in newSchedule:
                    self.static_jobs.append(job)

                inmediateJobs = newSchedule
            #compact static jobs for solver
            events = []
            for job in self.static_jobs:
                events.append([job[0], len(job[1].tasks)])
                events.append([job[0] + job[1].req_time, -len(job[1].tasks)])
            
            events.sort(key=lambda e:e[0])

            compactedJobs = []
            activeTasks = 0
            prevTime = None

            for time, tasks in events:
                #close if no active tasks
                if prevTime is not None and activeTasks > 0:
                    compactedJobs.append([prevTime, activeTasks, time])
                activeTasks += tasks
                prevTime = time

            
            self.solve(compactedJobs)

            print("\n---Inmediatos---")
            for job in inmediateJobs:
                print(f"  Job {job[1].id}: req_time={job[1].req_time}, initTime={job[0]}")

            print("---ALLOCATION---")
            #Schedule inmediate jobs
            for job in inmediateJobs:
                print(f"job: {job[1].id} tasks: {len(job[1].tasks)}")
                self.allocate(job[1])
                self.simulator.schedule(job[1].tasks)
                self.running_jobs.append(job[1])

            #Delay all jobs
            for job in self.schedule:
                print("JOB: "+str(job[1].id))
                print(f"cores used: {len(job[1].tasks)}")
                print("Init Time: "+str(job[0]))
                self.simulator.delay(job[1],job[0])
                if job[1] not in self.delayed_jobs:
                    self.delayed_jobs.append(job[1])


        else:
            return False
        
    def solve(self,  compactedJobs: list):
        print("Starting Solver")
        timestep = list(self.costs.keys())[1]
        T_max = list(self.costs.keys())[-1] + timestep
        M = T_max + sum(job[1].req_time for job in self.schedule) + 1

        #TODO: buscar algoritmo greedy euristico
            
        #define solver 
        solver = pywraplp.Solver.CreateSolver('SCIP')
        solver.SetTimeLimit(60_000)
        #problem variables
        slicesSingle = {}
        slicesIniOnly = {}
        slicesInter = {}
        slicesEndOnly = {}
        slicesOff = {}
        delta = {}
        initTime = {}
        overlap = {}

        for plannedJob in self.schedule:
            initTime[plannedJob[1].id] = solver.IntVar(plannedJob[1].submit_time, plannedJob[1].slack, f'iniTime_{plannedJob[1].id}') #initTime
            slicesSingle[plannedJob[1].id] = {}
            slicesIniOnly[plannedJob[1].id] = {}
            slicesInter[plannedJob[1].id] = {}
            slicesEndOnly[plannedJob[1].id] = {}
            slicesOff[plannedJob[1].id] = {}
            delta[plannedJob[1].id] = {}
            overlap[plannedJob[1].id] = {}

            for key in self.costs.keys():
                slicesSingle[plannedJob[1].id][key] = solver.BoolVar(f'sliceSingle_{plannedJob[1].id}_{key}') #slices true if initial and final are the same
                slicesIniOnly[plannedJob[1].id][key] = solver.BoolVar(f'sliceIniOnly_{plannedJob[1].id}_{key}') #slices only the initial one is true
                slicesInter[plannedJob[1].id][key] = solver.BoolVar(f'intermediate_slice_{plannedJob[1].id}_{key}') #slices the ones between initial and final are true
                slicesEndOnly[plannedJob[1].id][key] = solver.BoolVar(f'sliceEndOnly_{plannedJob[1].id}_{key}') #slices only the final one is true (can be the same as initial)
                slicesOff[plannedJob[1].id][key] = solver.BoolVar(f'inactive_slice_{plannedJob[1].id}_{key}') #slices true if job doesn't execute in it
                delta[plannedJob[1].id][key] = solver.IntVar(0, timestep, f'deltaTime_{key}_{plannedJob[1].id}') #Time the job spends in each slice
            for job2 in self.schedule:
                overlap[plannedJob[1].id][job2[1].id] = solver.BoolVar(f'overlap_{plannedJob[1].id}_{job2[1].id}') #True if two jobs overlap in execution
            for job2 in compactedJobs:
                overlap[plannedJob[1].id][job2[0]] = solver.BoolVar(f'overlap_{plannedJob[1].id}_{job2[0]}') #True if two jobs overlap in execution


        #function to minimize
        objective_terms = []
        for plannedJob in self.schedule:
            power = plannedJob[1].req_energy / plannedJob[1].req_time
            for key in self.costs.keys():
                objective_terms.append(power * self.costs[key] * delta[plannedJob[1].id][key])
        solver.Minimize(solver.Sum(objective_terms))


        #restrictions
        for plannedJob in self.schedule:
            solver.Add(initTime[plannedJob[1].id] + plannedJob[1].req_time <= plannedJob[1].slack) #we respect slacks
            solver.Add(solver.Sum(slicesIniOnly[plannedJob[1].id].values()) + solver.Sum(slicesSingle[plannedJob[1].id].values()) == 1) #Only one initial slice per job
            solver.Add(solver.Sum(slicesEndOnly[plannedJob[1].id].values()) + solver.Sum(slicesSingle[plannedJob[1].id].values()) == 1) #Only one final slice per job
            solver.Add(solver.Sum(delta[plannedJob[1].id].values()) == plannedJob[1].req_time) #All time per slices adds to required time for execution

            for key in self.costs.keys():
                #Job can only take one case
                solver.Add(
                    slicesOff[plannedJob[1].id][key] +
                    slicesInter[plannedJob[1].id][key] +
                    slicesSingle[plannedJob[1].id][key] +
                    slicesIniOnly[plannedJob[1].id][key] +
                    slicesEndOnly[plannedJob[1].id][key] == 1
                )

                # initTime is inside its initial slice
                solver.Add(initTime[plannedJob[1].id] - key >= -M * (1 - (slicesIniOnly[plannedJob[1].id][key] + slicesSingle[plannedJob[1].id][key])))
                solver.Add(key + timestep - initTime[plannedJob[1].id] >= -M * (1 - (slicesIniOnly[plannedJob[1].id][key] + slicesSingle[plannedJob[1].id][key])))

                # end time is inside final slice
                solver.Add(initTime[plannedJob[1].id] + plannedJob[1].req_time - key >= -M * (1 - (slicesEndOnly[plannedJob[1].id][key] + slicesSingle[plannedJob[1].id][key])))
                solver.Add(key + timestep - initTime[plannedJob[1].id] - plannedJob[1].req_time >= -M * (1 - (slicesEndOnly[plannedJob[1].id][key] + slicesSingle[plannedJob[1].id][key])))

                #Delta time is in single slice (delta = req_time)
                solver.Add(delta[plannedJob[1].id][key] - plannedJob[1].req_time >= -M * (1 - slicesSingle[plannedJob[1].id][key]))
                solver.Add(delta[plannedJob[1].id][key] - plannedJob[1].req_time <= M * (1 - slicesSingle[plannedJob[1].id][key]))

                #Delta time in initial slice (delta = end of step - initTime)
                solver.Add(delta[plannedJob[1].id][key] - (key + timestep - initTime[plannedJob[1].id]) >= -M * (1 - slicesIniOnly[plannedJob[1].id][key]))
                solver.Add(delta[plannedJob[1].id][key] - (key + timestep - initTime[plannedJob[1].id]) <=  M * (1 - slicesIniOnly[plannedJob[1].id][key]))

                #Delta time in intermediate slice (delta = timestep)
                solver.Add(delta[plannedJob[1].id][key] - timestep >= -M * (1 - slicesInter[plannedJob[1].id][key]))
                solver.Add(delta[plannedJob[1].id][key] - timestep <=  M * (1 - slicesInter[plannedJob[1].id][key]))

                #Delta time in final slice (delta = initTime + reqTime - key)
                solver.Add(delta[plannedJob[1].id][key] - (initTime[plannedJob[1].id] + plannedJob[1].req_time - key) >= -M * (1 - slicesEndOnly[plannedJob[1].id][key]))
                solver.Add(delta[plannedJob[1].id][key] - (initTime[plannedJob[1].id] + plannedJob[1].req_time - key) <=  M * (1 - slicesEndOnly[plannedJob[1].id][key]))

                #Delta time in inactive slice (delta = 0)
                solver.Add(delta[plannedJob[1].id][key] <=  M * (1 - slicesOff[plannedJob[1].id][key]))
                solver.Add(delta[plannedJob[1].id][key] >= -M * (1 - slicesOff[plannedJob[1].id][key]))

            #slices are in correct order
            solver.Add(solver.Sum(slicesIniOnly[plannedJob[1].id][key]*key for key in self.costs.keys()) <= solver.Sum(slicesEndOnly[plannedJob[1].id][key]*key for key in self.costs.keys())) #init before end
            solver.Add(solver.Sum(slicesIniOnly[plannedJob[1].id][key]*key for key in self.costs.keys()) <= solver.Sum(slicesInter[plannedJob[1].id][key]*key for key in self.costs.keys())) #init before intermediate
            solver.Add(solver.Sum(slicesInter[plannedJob[1].id][key]*key for key in self.costs.keys()) <= solver.Sum(slicesEndOnly[plannedJob[1].id][key]*key for key in self.costs.keys())) #inter before end

            #Overlaps between jobs    
            for job2 in self.schedule:

                a = solver.BoolVar(f'empieza_{plannedJob[1].id}_antes_de_{job2[1].id}')
                b = solver.BoolVar(f'empieza_{job2[1].id}_antes_de_{plannedJob[1].id}')

                #a is  true if initTime1 < initTime2 + req_time2
                solver.Add(initTime[job2[1].id] + job2[1].req_time - initTime[plannedJob[1].id] >= 1 - M * (1 - a))
                solver.Add(initTime[job2[1].id] + job2[1].req_time - initTime[plannedJob[1].id] <= M * a)

                #b is true if initTime2 < initTime1 + req_time1
                solver.Add(initTime[plannedJob[1].id] + plannedJob[1].req_time - initTime[job2[1].id] >= 1 - M * (1 - b))
                solver.Add(initTime[plannedJob[1].id] + plannedJob[1].req_time - initTime[job2[1].id] <= M * b)

                #overlap = a and b
                solver.Add(overlap[plannedJob[1].id][job2[1].id] >= a + b - 1)
                solver.Add(overlap[plannedJob[1].id][job2[1].id] <= a)
                solver.Add(overlap[plannedJob[1].id][job2[1].id] <= b)

            #overlaps with static jobs
            for job2 in compactedJobs:

                a = solver.BoolVar(f'empieza_{plannedJob[1].id}_antes_de_{job2[0]}')
                b = solver.BoolVar(f'empieza_{job2[0]}_antes_de_{plannedJob[1].id}')

                #a is  true if initTime1 < initTime2 + req_time2
                solver.Add(job2[2] - initTime[plannedJob[1].id] >= 1 - M * (1 - a))
                solver.Add(job2[2] - initTime[plannedJob[1].id] <= M * a)

                #b is true if initTime2 < initTime1 + req_time1
                solver.Add(initTime[plannedJob[1].id] + plannedJob[1].req_time - job2[0] >= 1 - M * (1 - b))
                solver.Add(initTime[plannedJob[1].id] + plannedJob[1].req_time - job2[0] <= M * b)

                #overlap = a and b
                solver.Add(overlap[plannedJob[1].id][job2[0]] >= a + b - 1)
                solver.Add(overlap[plannedJob[1].id][job2[0]] <= a)
                solver.Add(overlap[plannedJob[1].id][job2[0]] <= b)

            #node assigment
            #solver.Add(solver.Sum(len(job2[1].tasks) * overlap[plannedJob[1].id][job2[1].id] for job2 in self.schedule) <= sum(n.count_cores() for n in self.resources))
            allJobs = self.schedule.copy() + compactedJobs
            solver.Add(solver.Sum( self.get_tasks(job2[1]) * overlap[plannedJob[1].id][self.get_id(job2)] for job2 in allJobs) <= sum(n.count_cores() for n in self.resources))
            

            
        #Solve
        print()
        print("---SOLVING---")
        print()
        result = solver.Solve()

        print("solved")


        if  result == pywraplp.Solver.OPTIMAL:
            print("optimal solution")
        elif result == pywraplp.Solver.FEASIBLE:
            print("suboptimal solution")
        elif result == pywraplp.Solver.INFEASIBLE:
            print("INFEASIBLE — el problema no tiene solución")
            # Export model
            with open('model.lp', 'w') as f:
                f.write(solver.ExportModelAsLpFormat(False))
        else:
            print("ERROR")

        """
        print("--Solver Restrictions--")
        print("-overlap-")
        for plannedJob in self.schedule:
            for job2 in self.schedule:
                print(f"job1 {plannedJob[1].id} init {initTime[plannedJob[1].id].solution_value()} end {initTime[plannedJob[1].id].solution_value() + plannedJob[1].req_time}")
                print(f"job2 {job2[1].id} init {initTime[job2[1].id].solution_value()} end {initTime[job2[1].id].solution_value() + job2[1].req_time}")
                print(f"overlap {overlap[plannedJob[1].id][job2[1].id].solution_value()}")
        print("-nodes-")
        for plannedJob in self.schedule:
            print(f"job {plannedJob[1].id} Total tasks on overlap: {sum(len(plannedJob[1].tasks) * overlap[plannedJob[1].id][over].solution_value() for over in overlap[plannedJob[1].id].keys())} total cores { sum(n.count_cores() for n in self.resources)}")
        """

        newSchedule = []

        for job in self.schedule:
 
            newSchedule.append([initTime[job[1].id].solution_value(), job[1]])
            
        self.schedule = newSchedule

    def get_tasks(self, job):
        if isinstance(job, int):
            return job
        else:
            return len(job.tasks)
        
    def get_id(self, job):
        if isinstance(job[1], int):
            return job[0]
        else:
            return job[1].id

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