"""Code graders. success = db and facts and hygiene and trajectory, each also reported."""

from arl.evals.graders.outcome import grade_outcome
from arl.evals.graders.trajectory import grade_trajectory
from arl.evals.graders.types import GROUPS, Check, Verdict
from arl.evals.tasks import Task
from arl.evals.transcript import Transcript


def grade(task: Task, transcript: Transcript) -> Verdict:
    if transcript.task_id != task.id:
        raise ValueError(f"Transcript is for {transcript.task_id}, not {task.id}.")
    checks = grade_outcome(task, transcript) + grade_trajectory(task, transcript)
    return Verdict(checks, error=transcript.error)


__all__ = ["GROUPS", "Check", "Verdict", "grade"]
