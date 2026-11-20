"""Formula core (E7, ADR-003 part 2 option C): pure-Python parser and evaluator.

Independent of the cell store: the evaluator talks to a workbook through the `Env` protocol
(evaluator.py). Nothing here imports the rest of the engine.
"""
