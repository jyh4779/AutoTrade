"""Temporal split excludes labels crossing the train/test boundary."""


def temporal_split(samples, boundary, embargo_seconds=0):
    if embargo_seconds<0:raise ValueError('negative_embargo')
    train=[];test=[];excluded=[]
    for row in samples:
        if row['label_at']<row['signal_at']:raise ValueError('label_before_signal')
        if row['label_at']<boundary-embargo_seconds:
            train.append(row)
        elif row['signal_at']>=boundary+embargo_seconds:
            test.append(row)
        else:
            excluded.append(row)
    return train,test,excluded
