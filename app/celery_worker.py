import time
from celery import Celery

# Konfiguracja Celery z użyciem Redisa jako brokera wiadomości
celery_app = Celery(
    "worker",
    broker="redis://redis:6379/0",
    backend="redis://redis:6379/0",
)


@celery_app.task(name="process_file_task")
def process_file_task(filename: str, username: str):
  """To zadanie wykona się niezależnie w osobnym kontenerze-workerze!"""
  print(
      f"[CELERY WORKER] Rozpoczęto asynchroniczne przetwarzanie pliku:"
      f" {filename} dla użytkownika {username}"
  )
  time.sleep(5)  # Symulacja ciężkiej operacji (np. kompresja, parsowanie)
  print(f"[CELERY WORKER] Zakończono przetwarzanie pliku: {filename}")
  return {"status": "success", "filename": filename}

