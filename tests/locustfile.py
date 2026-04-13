import random
from locust import HttpUser, task, between

API_KEY = "rtk_-b2dCZTxppkHpJ_qGpPQHzvjPYRW9Syh3rt48k7lK3A"


class InfraUser(HttpUser):
    wait_time = between(0.5, 1.5)
    host = "http://localhost:8000"

    def on_start(self):
        self.headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        }

    @task(3)
    def health_check(self):
        self.client.get("/health", name="/health")

    @task(2)
    def get_metrics(self):
        self.client.get("/metrics", name="/metrics")

    @task(1)
    def poll_fake_job(self):
        # Tests auth + DB lookup without LLM
        self.client.get(
            "/api/v1/jobs/00000000-0000-0000-0000-000000000000",
            headers=self.headers,
            name="/api/v1/jobs/{id}",
        )