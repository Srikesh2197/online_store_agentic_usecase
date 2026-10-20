"""The eval harness: tasks, transcripts, graders, the runner and the report.

    task        a ticket plus what a correct run must leave behind and must not do
    trial       one attempt at one task, from a fresh database
    transcript  what the graders read about one trial, built from its JSONL trace
    grader      a pure function from (task, transcript) to checks that pass or fail
"""
