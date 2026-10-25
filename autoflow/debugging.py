"""Bounded descriptions of runtime inputs for node breakpoints."""
import reprlib


def describe_inputs(inputs, deferred):
    formatter = reprlib.Repr()
    formatter.maxstring = 500
    formatter.maxother = 500
    formatter.maxlist = formatter.maxtuple = formatter.maxdict = 12
    return [dict(name=name, type=type(value).__name__, value=formatter.repr(value),
                 deferred=name in deferred) for name, value in inputs.items()]
