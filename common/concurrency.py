"""Executor tasks must preserve tenant identity, tools mode and trace context."""
from contextvars import copy_context


def submit_with_context(executor, function, *args, **kwargs):
    return executor.submit(copy_context().run, function, *args, **kwargs)
