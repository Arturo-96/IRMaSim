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
                if plannedJob[2].id == job.id:
                    print("JOB REMOVED")
                    self.static_jobs.remove(plannedJob)
                    break
        while self.schedule_next_job():
            pass

    def  on_job_activation(self, jobs:  list):
        for job in jobs:
            self.schedule_delayed_job(job)

    def schedule_delayed_job(self, job):
        nodes = []
        for plannedJob in self.schedule:
            if job.id == plannedJob[2].id:
                nodes = plannedJob[1]
                self.static_jobs.append(plannedJob)
                self.schedule.remove(plannedJob)
                break
        
        self.allocate(job,nodes)
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
                print(f"Job: {job[2].id} start time: {job[0]}")
                for n in job[1]:
                    print(f"    node: {n[0]} cores: {n[1]}")

            print("\nstatic:")
            for job in self.static_jobs:
                print(f"Job: {job[2].id} start time: {job[0]}")
                for n in job[1]:
                    print(f"    node: {n[0]} cores: {n[1]}")

            inmediateJobs = []
            for job in self.pending_jobs:
                if job.slack and job.slack > 0:
                    self.schedule.append([-1,[],job])
                else:
                    inmediateJobs.append(job)

            self.pending_jobs = []
            
            print("JOBS:")
            for job in self.schedule:
                print("Job: "+str(job[2].id)+" slack: "+str(job[2].slack))

            if inmediateJobs:
                print("INMEDIATES")
                for job in inmediateJobs:
                    print("Job: "+str(job.id)+" slack: "+str(job.slack))

                #TODO: Anhadir abortar si se pasa de slack y testear mas
                newSchedule = self.secondary.schedule_jobs(inmediateJobs[0].submit_time, inmediateJobs, self.schedule.copy() + self.static_jobs.copy())
                for job in newSchedule:
                    self.static_jobs.append(job)

                inmediateJobs = newSchedule
            
            self.solve()

            print("\n---Inmediatos---")
            for job in inmediateJobs:
                print(f"  Job {job[2].id}: req_time={job[2].req_time}, initTime={job[0]}")

            print("---ALLOCATION---")
            #Schedule inmediate jobs
            for job in inmediateJobs:
                print(f"job: {job[2].id} tasks: {len(job[2].tasks)}")
                for n in job[1]:
                    print(f"    node {n[0]}: tasks to allocate: {n[1]}")
                self.allocate(job[2],job[1])
                self.simulator.schedule(job[2].tasks)
                self.running_jobs.append(job[2])

            #Delay all jobs
            for job in self.schedule:
                print("JOB: "+str(job[2].id))
                for n in job[1]:
                    print("node: "+str(n[0])+" cores: "+str(n[1]))
                print("Init Time: "+str(job[0]))
                self.simulator.delay(job[2],job[0])
                if job[2] not in self.delayed_jobs:
                    self.delayed_jobs.append(job[2])


        else:
            return False
        
    def solve(self):
        print("Starting Solver")
        timestep = list(self.costs.keys())[1]
        T_max = list(self.costs.keys())[-1] + timestep
        M = T_max + sum(job[2].req_time for job in self.schedule) + 1

        #TODO: mejorar las restricciones de solape
        #TODO: cambiar restricciones estaticas para usar ocupacion de recursos en intervalo de tiempo compactacion de trabajos
        #TODO: provar a usar un pool de cores en vez de ir nodo por nodo
        #TODO: hacer pruebas con worload sencillo que haga varios jobs tomar la hora mas barata a la vez
        #TODO: buscar algoritmo greedy euristico
        #TODO: buscar si se puede parar solver si la ejecucion es muy larga y quedarse con un resultado
            
        #define solver 
        solver = pywraplp.Solver.CreateSolver('SCIP')
        #problem variables
        slicesSingle = {}
        slicesIniOnly = {}
        slicesInter = {}
        slicesEndOnly = {}
        slicesOff = {}
        delta = {}
        initTime = {}
        nodes = {}
        overlap = {}
        endBefore = {}
        nodeCapacity = {}
        nodesInCommon = {}

        for n in self.resources:
            nodeCapacity[n.id] = n.count_cores()

        for plannedJob in self.schedule:
            initTime[plannedJob[2].id] = solver.IntVar(plannedJob[2].submit_time, plannedJob[2].slack, f'iniTime_{plannedJob[2].id}') #initTime
            nodes[plannedJob[2].id] = {}
            slicesSingle[plannedJob[2].id] = {}
            slicesIniOnly[plannedJob[2].id] = {}
            slicesInter[plannedJob[2].id] = {}
            slicesEndOnly[plannedJob[2].id] = {}
            slicesOff[plannedJob[2].id] = {}
            delta[plannedJob[2].id] = {}
            overlap[plannedJob[2].id] = {}
            endBefore[plannedJob[2].id] = {}
            nodesInCommon[plannedJob[2].id] = {}
            for n in self.resources:
                nodes[plannedJob[2].id][n.id] = solver.IntVar(0, n.count_cores(), f'node_{plannedJob[2].id}') #nodo
                nodesInCommon[plannedJob[2].id][n.id] = {}

            for key in self.costs.keys():
                slicesSingle[plannedJob[2].id][key] = solver.BoolVar(f'sliceSingle_{plannedJob[2].id}_{key}') #slices true if initial and final are the same
                slicesIniOnly[plannedJob[2].id][key] = solver.BoolVar(f'sliceIniOnly_{plannedJob[2].id}_{key}') #slices only the initial one is true
                slicesInter[plannedJob[2].id][key] = solver.BoolVar(f'intermediate_slice_{plannedJob[2].id}_{key}') #slices the ones between initial and final are true
                slicesEndOnly[plannedJob[2].id][key] = solver.BoolVar(f'sliceEndOnly_{plannedJob[2].id}_{key}') #slices only the final one is true (can be the same as initial)
                slicesOff[plannedJob[2].id][key] = solver.BoolVar(f'inactive_slice_{plannedJob[2].id}_{key}') #slices true if job doesn't execute in it
                delta[plannedJob[2].id][key] = solver.IntVar(0, timestep, f'deltaTime_{key}_{plannedJob[2].id}') #Time the job spends in each slice
            for job2 in self.schedule:
                overlap[plannedJob[2].id][job2[2].id] = solver.BoolVar(f'overlap_{plannedJob[2].id}_{job2[2].id}') #True if two jobs overlap in execution
                endBefore[plannedJob[2].id][job2[2].id] = solver.BoolVar(f'Ends_before_{plannedJob[2].id}_{job2[2].id}') #True if job 1 ends before job 2
            for job2 in self.static_jobs:
                overlap[plannedJob[2].id][job2[2].id] = solver.BoolVar(f'overlap_{plannedJob[2].id}_{job2[2].id}') #True if two jobs overlap in execution
                endBefore[plannedJob[2].id][job2[2].id] = solver.BoolVar(f'Ends_before_{plannedJob[2].id}_{job2[2].id}') #True if job 1 ends before job 2
            
        for job in self.static_jobs:
            endBefore[job[2].id] = {}
            for job2 in self.schedule:
                endBefore[job[2].id][job2[2].id] = solver.BoolVar(f'Ends_before_{job[2].id}_{job2[2].id}') #True if job 1 ends before job 2


        #function to minimize
        objective_terms = []
        for plannedJob in self.schedule:
            power = plannedJob[2].req_energy / plannedJob[2].req_time
            for key in self.costs.keys():
                objective_terms.append(power * self.costs[key] * delta[plannedJob[2].id][key])
        solver.Minimize(solver.Sum(objective_terms))


        #restrictions
        for plannedJob in self.schedule:
            solver.Add(initTime[plannedJob[2].id] + plannedJob[2].req_time <= plannedJob[2].slack) #we respect slacks
            solver.Add(solver.Sum(slicesIniOnly[plannedJob[2].id].values()) + solver.Sum(slicesSingle[plannedJob[2].id].values()) == 1) #Only one initial slice per job
            solver.Add(solver.Sum(slicesEndOnly[plannedJob[2].id].values()) + solver.Sum(slicesSingle[plannedJob[2].id].values()) == 1) #Only one final slice per job
            solver.Add(solver.Sum(delta[plannedJob[2].id].values()) == plannedJob[2].req_time) #All time per slices adds to required time for execution
            solver.Add(solver.Sum(nodes[plannedJob[2].id].values()) == len(plannedJob[2].tasks)) #cores taken equal number of tasks

            for key in self.costs.keys():
                #Job can only take one case
                solver.Add(
                    slicesOff[plannedJob[2].id][key] +
                    slicesInter[plannedJob[2].id][key] +
                    slicesSingle[plannedJob[2].id][key] +
                    slicesIniOnly[plannedJob[2].id][key] +
                    slicesEndOnly[plannedJob[2].id][key] == 1
                )

                # initTime is inside its initial slice
                solver.Add(initTime[plannedJob[2].id] - key >= -M * (1 - (slicesIniOnly[plannedJob[2].id][key] + slicesSingle[plannedJob[2].id][key])))
                solver.Add(key + timestep - initTime[plannedJob[2].id] >= -M * (1 - (slicesIniOnly[plannedJob[2].id][key] + slicesSingle[plannedJob[2].id][key])))

                # end time is inside final slice
                solver.Add(initTime[plannedJob[2].id] + plannedJob[2].req_time - key >= -M * (1 - (slicesEndOnly[plannedJob[2].id][key] + slicesSingle[plannedJob[2].id][key])))
                solver.Add(key + timestep - initTime[plannedJob[2].id] - plannedJob[2].req_time >= -M * (1 - (slicesEndOnly[plannedJob[2].id][key] + slicesSingle[plannedJob[2].id][key])))

                #Delta time is in single slice (delta = req_time)
                solver.Add(delta[plannedJob[2].id][key] - plannedJob[2].req_time >= -M * (1 - slicesSingle[plannedJob[2].id][key]))
                solver.Add(delta[plannedJob[2].id][key] - plannedJob[2].req_time <= M * (1 - slicesSingle[plannedJob[2].id][key]))

                #Delta time in initial slice (delta = end of step - initTime)
                solver.Add(delta[plannedJob[2].id][key] - (key + timestep - initTime[plannedJob[2].id]) >= -M * (1 - slicesIniOnly[plannedJob[2].id][key]))
                solver.Add(delta[plannedJob[2].id][key] - (key + timestep - initTime[plannedJob[2].id]) <=  M * (1 - slicesIniOnly[plannedJob[2].id][key]))

                #Delta time in intermediate slice (delta = timestep)
                solver.Add(delta[plannedJob[2].id][key] - timestep >= -M * (1 - slicesInter[plannedJob[2].id][key]))
                solver.Add(delta[plannedJob[2].id][key] - timestep <=  M * (1 - slicesInter[plannedJob[2].id][key]))

                #Delta time in final slice (delta = initTime + reqTime - key)
                solver.Add(delta[plannedJob[2].id][key] - (initTime[plannedJob[2].id] + plannedJob[2].req_time - key) >= -M * (1 - slicesEndOnly[plannedJob[2].id][key]))
                solver.Add(delta[plannedJob[2].id][key] - (initTime[plannedJob[2].id] + plannedJob[2].req_time - key) <=  M * (1 - slicesEndOnly[plannedJob[2].id][key]))

                #Delta time in inactive slice (delta = 0)
                solver.Add(delta[plannedJob[2].id][key] <=  M * (1 - slicesOff[plannedJob[2].id][key]))
                solver.Add(delta[plannedJob[2].id][key] >= -M * (1 - slicesOff[plannedJob[2].id][key]))

            #Overlaps between jobs    
            for job2 in self.schedule:
                if plannedJob[2].id == job2[2].id:
                    #same job we ignore
                    continue

                #if left side positive no overlap
                solver.Add(
                    initTime[job2[2].id] - initTime[plannedJob[2].id] - plannedJob[2].req_time >= -M * (1 - endBefore[plannedJob[2].id][job2[2].id])
                )
                #if job 1 ends before job 2 then no overlap
                solver.Add(overlap[plannedJob[2].id][job2[2].id] <= 1 - endBefore[plannedJob[2].id][job2[2].id])

                #if no job ends before the other then overlap
                solver.Add(overlap[plannedJob[2].id][job2[2].id] >= 1 - endBefore[plannedJob[2].id][job2[2].id] - endBefore[job2[2].id][plannedJob[2].id])

            #overlaps with static jobs
            for job2 in self.static_jobs:
                #if left side positive no overlap
                solver.Add(
                    job2[0] - initTime[plannedJob[2].id] - plannedJob[2].req_time >= -M * (1 - endBefore[plannedJob[2].id][job2[2].id])
                )
                #if job 1 ends before job 2 then no overlap
                solver.Add(overlap[plannedJob[2].id][job2[2].id] <= 1 - endBefore[plannedJob[2].id][job2[2].id])

                #if no job ends before the other then overlap
                solver.Add(overlap[plannedJob[2].id][job2[2].id] >= 1 - endBefore[plannedJob[2].id][job2[2].id] - endBefore[job2[2].id][plannedJob[2].id])

            #node assigment
            for n in self.resources:

                #cores used by job1
                load = [nodes[plannedJob[2].id][n.id]]

                for job2 in self.schedule:
                    if plannedJob[2].id == job2[2].id:
                        #same job we ignore
                        continue
                        
                    #cores that job2 takes in node at the same time that job1
                    nodesInCommon[plannedJob[2].id][n.id][job2[2].id] = solver.IntVar(0, nodeCapacity[n.id], f'cores_that_{job2[2].id}_use_at_the_same_time_that_{plannedJob[2].id}_in_{n.id}')

                    #If no overlap then cores = 0
                    solver.Add(nodesInCommon[plannedJob[2].id][n.id][job2[2].id] <= nodeCapacity[n.id] * overlap[plannedJob[2].id][job2[2].id])
                    #overlap cores must be less or equal than the cores assigned to job2
                    solver.Add(nodesInCommon[plannedJob[2].id][n.id][job2[2].id] <= nodes[job2[2].id][n.id])
                    #if overlap cores in common must be equal to cores in job 2
                    solver.Add(nodesInCommon[plannedJob[2].id][n.id][job2[2].id] >= nodes[job2[2].id][n.id] - nodeCapacity[n.id] * (1 - overlap[plannedJob[2].id][job2[2].id]))

                    #add cores used by job2
                    load.append(nodesInCommon[plannedJob[2].id][n.id][job2[2].id])

                #static jobs
                for job2 in self.static_jobs:
                    #cores that job2 takes in node at the same time that job1
                    nodesInCommon[plannedJob[2].id][n.id][job2[2].id] = solver.IntVar(0, nodeCapacity[n.id], f'cores_that_{job2[2].id}_use_at_the_same_time_that_{plannedJob[2].id}_in_{n.id}')

                    #If no overlap then cores = 0
                    solver.Add(nodesInCommon[plannedJob[2].id][n.id][job2[2].id] <= nodeCapacity[n.id] * overlap[plannedJob[2].id][job2[2].id])
                    #overlap cores must be less or equal than the cores assigned to job2
                    nTasks = 0
                    for node in job2[1]:
                        if node[0] == n.id:
                            nTasks = node[1]
                    solver.Add(nodesInCommon[plannedJob[2].id][n.id][job2[2].id] <= nTasks)
                    #if overlap cores in common must be equal to cores in job 2
                    solver.Add(nodesInCommon[plannedJob[2].id][n.id][job2[2].id] >= nTasks - nodeCapacity[n.id] * (1 - overlap[plannedJob[2].id][job2[2].id]))

                    #add cores used by job2
                    load.append(nodesInCommon[plannedJob[2].id][n.id][job2[2].id])


                #All cores used in an instant do not exeed the node capacity
                solver.Add(solver.Sum(load) <= nodeCapacity[n.id])
            
        #Solve
        print()
        print("---SOLVING---")
        print()
        result = solver.Solve()

        print("solved")

        if  True:
                print("INFEASIBLE — el problema no tiene solución")
                # Export model
                with open('model.lp', 'w') as f:
                    f.write(solver.ExportModelAsLpFormat(False))

        newSchedule = []

        for job in self.schedule:
            solvedNodes = []
            for n in nodes[job[2].id].keys():
                solvedNodes.append([n,nodes[job[2].id][n].solution_value()])
            newSchedule.append([initTime[job[2].id].solution_value(), solvedNodes, job[2]])
            
        self.schedule = newSchedule

    def on_end_step(self):
        pass

    def on_end_simulation(self):
        pass

    def set_costs(self, costs: dict):
        self.costs = costs

    def set_secondary(self, manager: WorkloadManager):
        self.secondary = manager

    def allocate(self, job: Job, nodes: list):
        tasks = job.tasks.copy()
        for node in nodes:
            for n in self.resources:
                if node[0] == n.id:
                    x = node[1]
                    for core in n.idle_cores():
                        if len(tasks) == 0:
                            return
                        if x > 0:
                            task = tasks.pop(0)
                            task.allocate(core.full_id())
                        else:
                            break
                

    #Not used for now
    def deallocate(self, task: Task):
        for resource in range(len(self.resources)):
           if self.resources[resource][1] == 0 and self.resources[resource][0] == task.resource:
               self.resources[resource][1] = 1
               self.idle_resources += 1
               break