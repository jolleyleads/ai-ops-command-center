"""Bounded, durable records of observed workflow stages (no private reasoning)."""
def with_activity(previous, update, timestamp):
    progress={**previous, **update, 'updated_at':timestamp}
    events=list(previous.get('activity') or [])
    stage=update.get('stage')
    if stage and (not events or events[-1]['stage']!=stage):
        events.append({'stage':stage,'at':timestamp})
    progress['activity']=events[-60:]
    return progress
