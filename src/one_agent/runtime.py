"""Effective rules derive exclusively from controls already delivered to this replay."""
import copy
from .ingestion import load_goals

def effective_goals(store, pack):
    config = copy.deepcopy(load_goals(pack))
    for control in store.applied_controls:
        if control['type'] == 'goal_rule_corrected':
            for rule in config['goals']:
                if rule['goal_id'] == control['goal_id']:
                    rule['success'].update(control['new_success'])
    return config
