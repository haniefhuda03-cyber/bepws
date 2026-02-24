import sys
import os
import logging
sys.path.append(os.getcwd())

from app import create_app, scheduler

logging.basicConfig(level=logging.INFO)

def check():
    app = create_app()
    with app.app_context():
        jobs = scheduler.get_jobs()
        print(f"JOBS_COUNT={len(jobs)}")
        for j in jobs:
            print(f"JOB={j.id}")

if __name__ == "__main__":
    check()
