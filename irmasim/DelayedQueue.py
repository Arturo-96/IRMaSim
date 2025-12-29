from irmasim.Job import Job
import math
import logging
import numpy

class DelayedQueue:

    def __init__(self):
        self.future_jobs = []
        self.submitted_jobs = []
        self.finished_jobs = []

    def add_job(self, job: Job, time: int):
        self.future_jobs.append([job,time])
        self.future_jobs.sort(key=lambda x: x[1])

    def add_jobs(self, jobs: list):
        self.future_jobs.extend(jobs)
        self.future_jobs.sort(key=lambda x: x.submit_time)

    def get_next_jobs(self, now: float):
        if len(self.future_jobs) > 0:
            incoming_jobs = [job for job in self.future_jobs if job[1] <= now]
            self.submitted_jobs.extend(incoming_jobs)
            self.future_jobs = [job for job in self.future_jobs if job not in incoming_jobs]
            return [job[0] for  job in incoming_jobs]
        else:
            raise Exception("No jobs in queue")

    def get_next_step(self):
        if self.future_jobs:
            return self.future_jobs[0][1]
        else:
            return math.inf
        
    def get_job_counts(self):
        running  = sum([1 for job in self.submitted_jobs if job[0].start_time < math.inf])
        return len(self.future_jobs), len(self.submitted_jobs) - running, running, len(self.finished_jobs)


    def __str__(self):
        return "future = [ " + ", ".join([str(job[0].id) for job in self.future_jobs]) + " ]" \
            + " submitted = [ " + ", ".join([str(job[0].id) for job in self.submitted_jobs]) + " ]" \
            + " finished = [ " + ", ".join([str(job[0].id) for job in self.finished_jobs]) + " ]"
