from datetime import timedelta

def compare(actual, operator, expected=None, upper=None, tolerance=None):
    a=float(actual) if isinstance(actual,(int,float)) else actual
    e=float(expected) if isinstance(expected,(int,float)) else expected
    if operator in ('eq','equals'): return a==e
    if operator in ('ne','not_equals'): return a!=e
    if operator=='gt': return a>e
    if operator=='gte': return a>=e
    if operator=='lt': return a<e
    if operator=='lte': return a<=e
    if operator=='between': return float(expected)<=float(actual)<=float(upper)
    if operator=='approx':
        if tolerance is None: raise ValueError('Approximate comparison requires an engineer-specified tolerance.')
        return abs(float(actual)-float(expected))<=float(tolerance)
    raise ValueError(f'Unsupported operator: {operator}')

def evaluate_definition(definition, samples_by_point):
    conditions=definition.get('conditions',[])
    if not conditions: return {'status':'not_testable','reason':'No deterministic test conditions have been defined.'}
    outcomes=[]; missing=[]
    for c in conditions:
        op=c.get('operator')
        if op=='response_within':
            trigger_name=c.get('trigger_point'); response_name=c.get('response_point')
            triggers=[s for s in samples_by_point.get(trigger_name,[]) if s.get('quality')=='good' and compare(s['value'],c.get('trigger_operator','eq'),c.get('trigger_value'))]
            responses=[s for s in samples_by_point.get(response_name,[]) if s.get('quality')=='good']
            if not samples_by_point.get(trigger_name) or not samples_by_point.get(response_name):
                missing.extend([x for x in (trigger_name,response_name) if not samples_by_point.get(x)])
                continue
            if not triggers:
                outcomes.append({'condition':c,'passed':False,'reason':'No qualifying trigger event was found in the retained trend window.'})
                continue
            trigger=triggers[-1]; window=float(c['window_seconds']); deadline=trigger['sampled_at']+timedelta(seconds=window)
            candidates=[s for s in responses if trigger['sampled_at']<=s['sampled_at']<=deadline]
            passed=any(compare(s['value'],c['response_operator'],c.get('response_value'),c.get('upper'),c.get('tolerance')) for s in candidates)
            outcomes.append({'condition':c,'passed':passed,'trigger_time':trigger['sampled_at'].isoformat(),'response_samples':len(candidates)})
        else:
            name=c.get('point_name'); good=[s for s in samples_by_point.get(name,[]) if s.get('quality')=='good']
            if not good:
                missing.append(name or '(unnamed point)'); continue
            latest=good[-1]
            passed=compare(latest['value'],op,c.get('value'),c.get('upper'),c.get('tolerance'))
            outcomes.append({'condition':c,'passed':passed,'observed':latest['value'],'sampled_at':latest['sampled_at'].isoformat()})
    if missing: return {'status':'not_testable','reason':'Missing good-quality trend samples for required point(s).','missing_points':sorted(set(missing)),'conditions':outcomes}
    if len(outcomes)!=len(conditions): return {'status':'not_testable','reason':'One or more conditions could not be evaluated.','conditions':outcomes}
    passed=[x['passed'] for x in outcomes]
    ok=all(passed) if definition.get('logic','all')=='all' else any(passed)
    return {'status':'pass' if ok else 'fail','logic':definition.get('logic','all'),'conditions':outcomes}

def evaluate(rule, values, timestamps=None):
    missing=[p for p in rule.get('required_points',[]) if p not in values]
    if missing: return {'status':'not_testable','reason':'Required point values are missing','missing_points':missing,'observed':values}
    return {'status':'requires_engineer_test_definition','reason':'Rule needs a reviewed, deterministic acceptance expression before automated verdicts.','observed':values,'rule_id':rule.get('id')}
