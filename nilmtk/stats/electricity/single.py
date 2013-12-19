"""Statistics applicable to a single appliance / circuit / mains split.

In general, these functions each take a DataFrame representing a single
appliance / circuit / mains split.
"""
from __future__ import print_function, division
import scipy.stats as stats
import numpy as np
import pandas as pd
from matplotlib.dates import SEC_PER_HOUR
import copy

def sample_period(data):
    """Estimate the sample period in seconds.

    Find the sample period by finding the stats.mode of the 
    forward difference.  Only use the first 100 samples (for speed).

    Parameters
    ----------
    data : pandas.DataFrame or Series or DatetimeIndex

    Returns
    -------
    period : float
        Sample period in seconds.
    """
    if isinstance(data, (pd.DataFrame, pd.Series)):
        index = data.index
    elif isinstance(data, pd.DatetimeIndex):
        index = data
    else:
        raise TypeError('wrote type for `data`.')

    fwd_diff = np.diff(index.values[:100]).astype(np.float)
    mode_fwd_diff = stats.mode(fwd_diff)[0][0]
    period = mode_fwd_diff / 1E9
    return period
    

def dropout_rate(df):
    """The proportion of samples that have been lost.

    Parameters
    ----------
    df : pandas.DataFrame

    Returns
    -------
    rate : float [0,1]
        The proportion of samples that have been lost; where 
        1 means that all samples have been lost and 
        0 means that no samples have been lost.
    """
    duration = df.index[-1] - df.index[0]        
    n_expected_samples = duration.total_seconds() / sample_period(df)
    return 1 - (df.index.size / n_expected_samples)


def hours_on(series, on_power_threshold=5, max_sample_period=None):
    """Returns a float representing the number of hours this channel
    has been above threshold.

    Parameters
    ----------
    series : pandas.Series

    on_power_threshold : float or int, optional, default = 5
        Threshold which defines the distinction between "on" and "off".  Watts.

    max_sample_period : float or int, optional 
        The maximum allowed sample period in seconds.  This is used
        where, for example, we have a wireless meter which is supposed
        to report every `K` seconds and we assume that if we don't
        hear from it for more than `max_sample_period=K*3` seconds
        then the sensor (and appliance) have been turned off from the
        wall. If we find a sample above `on_power_threshold` at time
        `t` and there are more than `max_sample_period` seconds until
        the next sample then we assume that the appliance has only
        been on for `max_sample_period` seconds after time `t`.

    Returns
    -------
    hours_above_threshold : float


    See Also
    --------
    kwh
    joules
    """

    i_above_threshold = np.where(series[:-1] >= on_power_threshold)[0]
    td_above_thresh = (series.index[i_above_threshold+1].values -
                       series.index[i_above_threshold].values)
    if max_sample_period is not None:
        td_above_thresh[td_above_thresh > max_sample_period] = max_sample_period

    secs_on = td_above_thresh.sum().astype('timedelta64[s]').astype(np.int64)
    return secs_on / SEC_PER_HOUR


def energy(series, max_sample_period=None, unit='kwh'):
    """Returns a float representing the quantity of energy this 
    channel consumed.

    Parameters
    ----------
    series : pd.Series

    max_sample_period : float or int, optional 
        The maximum allowed sample period in seconds.  If we find a
        sample above `on_power_threshold` at time `t` and there are
        more than `max_sample_period` seconds until the next sample
        then we assume that the appliance has only been on for
        `max_sample_period` seconds after time `t`.  This is used where,
        for example, we have a wireless meter which is supposed to
        report every `K` seconds and we assume that if we don't hear
        from it for more than `max_sample_period=K*3` seconds then the
        sensor (and appliance) have been turned off from the wall.

    unit : {'kwh', 'joules'}

    Returns
    -------
    _energy : float

    See Also
    --------
    hours_on
    """
    td = np.diff(series.index.values)
    if max_sample_period is not None:
        td = np.where(td > max_sample_period, max_sample_period, td)
    td_secs = td / np.timedelta64(1, 's')
    joules = (td_secs * series.values[:-1]).sum()

    if unit == 'kwh':
        JOULES_PER_KWH = 3600000
        _energy = joules / JOULES_PER_KWH
    elif unit == 'joules':
        _energy = joules
    else:
        raise ValueError('unrecognised value for `unit`.')

    return _energy


def usage_per_period(series, freq, tz_convert=None, on_power_threshold=5, 
                     max_dropout_rate=0.4, verbose=False, 
                     energy_unit='kwh', max_sample_period=None):
    """Calculate the usage (hours on and kwh) per time period.

    Parameters
    ----------
    series : pd.Series

    freq : str
        see _indicies_of_periods() for acceptable values.

    on_power_threshold : float or int, optional, default = 5
        Threshold which defines the distinction between "on" and "off".  Watts.

    max_dropout_rate : float (0,1), optional, default = 0.4
        Remove any row which has a worse (larger) dropout rate.
    
    verbose : boolean, optional, default = False
        if True then print more information
    
    energy_unit : {'kwh', 'joules'}, optional

    max_sample_period : float or int, optional 
        The maximum allowed sample period in seconds.  If we find a
        sample above `on_power_threshold` at time `t` and there are
        more than `max_sample_period` seconds until the next sample
        then we assume that the appliance has only been on for
        `max_sample_period` seconds after time `t`.  This is used where,
        for example, we have a wireless meter which is supposed to
        report every `K` seconds and we assume that if we don't hear
        from it for more than `max_sample_period=K*3` seconds then the
        sensor (and appliance) have been turned off from the wall.

    Returns
    -------
    usage : pd.DataFrame
        One row per period (as defined by `freq`).  
        Index is PeriodIndex (UTC).
        Columns:
            hours_on
            <`energy_unit`>

    Examples
    --------
    Say we have loaded fridge data from house_1 in REDD into `fridge` and we
    want to see how it was used each day:

    >>> usage_per_period(fridge, 'D')

                 hours_on       kwh
    2011-04-18        NaN       NaN
    2011-04-19  23.999444  1.104083
    2011-04-20  23.998889  1.293223
    2011-04-21  23.998889  1.138540
    ...
    2011-05-22  23.832500  2.042271
    2011-05-23  23.931111  1.394619
    2011-05-24        NaN       NaN 

    Hmmm... why does the fridge appear to be on for 24 hours per day?
    Inspecting the fridge.plot(), we find that the fridge rarely ever
    gets below this function's default on_power_threshold of 5 Watts,
    so let's specify a larger threshold:

    >>> usage_per_period(fridge, 'D', on_power_threshold=100)

                hours_on       kwh
    2011-04-18       NaN       NaN
    2011-04-19  5.036111  1.104083
    2011-04-20  5.756667  1.293223
    2011-04-21  4.931667  1.138540
    2011-04-22  4.926111  1.076958
    2011-04-23  6.099167  1.357812
    2011-04-24  6.373056  1.361579
    2011-04-25  6.496667  1.441966
    2011-04-26  6.381389  1.404637
    2011-04-27  5.558611  1.196464
    2011-04-28  6.668611  1.478141
    2011-04-29  6.493056  1.446713
    2011-04-30  5.885278  1.263918
    2011-05-01  5.983611  1.351419
    2011-05-02  5.398333  1.167111
    2011-05-03       NaN       NaN
    2011-05-04       NaN       NaN
    2011-05-05       NaN       NaN
    2011-05-06       NaN       NaN
    2011-05-07  5.112222  1.120848
    2011-05-08  6.349722  1.413897
    2011-05-09  7.270833  1.573199
    2011-05-10  5.997778  1.249120
    2011-05-11  5.685556  1.264841
    2011-05-12  7.153333  1.478244
    2011-05-13  5.949444  1.306350
    2011-05-14  6.446944  1.415302
    2011-05-15  5.958333  1.275853
    2011-05-16  6.801944  1.501816
    2011-05-17  5.836389  1.342787
    2011-05-18  5.254444  1.164683
    2011-05-19  6.234444  1.397851
    2011-05-20  5.814444  1.265143
    2011-05-21  6.738333  1.498687
    2011-05-22  9.308056  2.042271
    2011-05-23  6.127778  1.394619
    2011-05-24       NaN       NaN

    That looks sensible!  Now, let's find out why the cause of the NaNs by 
    setting verbose=True:
    
    >>> usage_per_period(fridge, 'D', on_power_threshold=100, verbose=True)

    Insufficient samples for 2011-04-18; n samples = 13652; dropout_rate = 52.60%
                     start = 2011-04-18 09:22:13-04:00
                       end = 2011-04-18 23:59:57-04:00
    Insufficient samples for 2011-05-03; n samples = 16502; dropout_rate = 42.70%
                     start = 2011-05-03 00:00:03-04:00
                       end = 2011-05-03 17:33:17-04:00
    No data available for    2011-05-04
    No data available for    2011-05-05
    Insufficient samples for 2011-05-06; n samples = 12465; dropout_rate = 56.72%
                     start = 2011-05-06 10:51:50-04:00
                       end = 2011-05-06 23:59:58-04:00
    Insufficient samples for 2011-05-24; n samples = 13518; dropout_rate = 53.06%
                     start = 2011-05-24 00:00:02-04:00
                       end = 2011-05-24 15:56:34-04:00
    Out[209]: 
                hours_on       kwh
    2011-04-18       NaN       NaN
    2011-04-19  5.036111  1.104083
    2011-04-20  5.756667  1.293223
    ...

    Ah, OK, there are insufficient samples for the periods with NaNs.  We could
    set max_dropout_rate to a number closer to 1, but that would give us data
    for days where there isn't much data for that day.

    """

    assert(0 <= max_dropout_rate <= 1)

    period_range, boundaries = _indicies_of_periods(series.index, freq)
    name = str(series.name)
    hours_on_series = pd.Series(index=period_range, dtype=np.float, 
                                name=name+' hours on')
    energy_series = pd.Series(index=period_range, dtype=np.float, 
                              name=name+' '+energy_unit)

    MAX_SAMPLES_PER_PERIOD = _secs_per_period_alias(freq) / sample_period(series)
    MIN_SAMPLES_PER_PERIOD = (MAX_SAMPLES_PER_PERIOD *
                              (1-max_dropout_rate))

    for period in period_range:
        try:
            period_start_i, period_end_i = boundaries[period]
        except KeyError:
            if verbose:
                print("No data available for   ",
                      period.strftime('%Y-%m-%d'))
            continue

        data_for_period = series[period_start_i:period_end_i]
        if data_for_period.size < MIN_SAMPLES_PER_PERIOD:
            if verbose:
                dropout_rate = (1 - (data_for_period.size / 
                                     MAX_SAMPLES_PER_PERIOD))
                print("Insufficient samples for ",
                      period.strftime('%Y-%m-%d'),
                      "; n samples = ", data_for_period.size,
                      "; dropout_rate = {:.2%}".format(dropout_rate), sep='')
                print("                 start =", data_for_period.index[0])
                print("                   end =", data_for_period.index[-1])
            continue

        hours_on_series[period] = hours_on(data_for_period, 
                                           on_power_threshold=on_power_threshold,
                                           max_sample_period=max_sample_period)
        energy_series[period] = energy(data_for_period, 
                                       max_sample_period=max_sample_period, 
                                       unit=energy_unit)

    return pd.DataFrame({'hours_on': hours_on_series,
                         energy_unit: energy_series})


#------------------------ HELPER FUNCTIONS -------------------------

def _secs_per_period_alias(alias):
    """The duration of a period alias in seconds."""
    dr = pd.date_range('00:00', periods=2, freq=alias)
    return (dr[-1] - dr[0]).total_seconds()


def _indicies_of_periods(datetime_index, freq, use_local_time=True):
    """Find which elements of `datetime_index` fall into each period
    of a regular periods with frequency `freq`.  Uses some tricks to do
    this more efficiently that appears possible with native Pandas tools.

    Parameters
    ----------
    datetime_index : pd.tseries.index.DatetimeIndex

    freq : str
        one of the following:
        'A' for yearly
        'M' for monthly
        'D' for daily
        'H' for hourly
        'T' for minutely

    use_local_time : boolean, optional, default=True
        If True then start and end each time period at appropriate local times.
        e.g. if `freq='D'` and:
            `use_local_time=True` then divide at midnight *local time* or if
            `use_local_time=False` then divide at midnight UTC

    Returns
    -------
    periods : pd.tseries.period.PeriodIndex

    boundaries : dict
        Each key is a pd.tseries.period.Period
        Each value is a tuple of ints:
        (<start index into `datetime_index` for period>, <end index>)

    Examples
    --------
    Say you have a pd.Series with data covering a month:

    >>> series.index
    <class 'pandas.tseries.index.DatetimeIndex'>
    [2011-04-18 09:22:13, ..., 2011-05-24 15:56:34]
    Length: 745878, Freq: None, Timezone: US/Eastern

    You want to divide it up into day-sized chunks, starting and ending each
    chunk at midnight local time:

    >>> periods, boundaries = _indicies_of_periods(series.index, freq='D')

    >>> periods
    <class 'pandas.tseries.period.PeriodIndex'>
    freq: D
    [2011-04-18, ..., 2011-05-24]
    length: 37

    >>> boundaries
    {Period('2011-04-18', 'D'): (0, 13652),
     Period('2011-04-19', 'D'): (13652, 34926),
     Period('2011-04-20', 'D'): (34926, 57310),
     ...
     Period('2011-05-23', 'D'): (710750, 732360),
     Period('2011-05-24', 'D'): (732360, 745878)}

    Now, say that we want chomp though our data a day at a time:

    >>> for period in periods:
    >>>     start_i, end_i = boundaries[period]
    >>>     data_for_day = series.iloc[start_i:end_i]
    >>>     # do something with data_for_day

    """

    if use_local_time:
        datetime_index = copy.copy(datetime_index)
        ts = datetime_index[0] # 'ts' = timestamp
        # Calculate timezone offset relative to UTC
        tz_offset = ts.replace(tzinfo=None) - ts.tz_convert('UTC').replace(tzinfo=None)
        datetime_index = datetime_index.tz_convert('UTC') + tz_offset
        # We end up with a datetime_index being tz-aware, localised to UTC
        # but offset so that the UTC time is the same as the local time
        # e.g. if, prior to conversion, 
        #     datetime_index[0] = 12:00-04:00 US/Eastern
        # then after conversion:
        #     datetime_index[0] = 12:00+00:00 UTC

    periods = pd.period_range(datetime_index[0], datetime_index[-1], freq=freq)

    # Declare and initialise some constants and variables used
    # during the loop...

    # Find the minimum sample period.
    MIN_SAMPLE_PERIOD = int(sample_period(datetime_index))
    MAX_SAMPLES_PER_PERIOD = int(_secs_per_period_alias(freq) / MIN_SAMPLE_PERIOD)
    MAX_SAMPLES_PER_2_PERIODS = MAX_SAMPLES_PER_PERIOD * 2
    n_rows_processed = 0
    boundaries = {}
    for period in periods:
        # The simplest way to get data for just a single period is to use
        # data_for_day = datetime_index[period.strftime('%Y-%m-%d')]
        # but this takes about 300ms per call on my machine.
        # So we take advantage of several features of the data to achieve
        # a 300x speedup:
        # 1. We use the fact that the data is sorted in order, hence 
        #    we can chomp through it in order.
        # 2. MAX_SAMPLES_PER_PERIOD sets an upper bound on the number of
        #    datapoints per period.  The code is conservative and uses 
        #    MAX_SAMPLES_PER_2_PERIODS. We only search through a small subset
        #    of the available data.

        end_index = n_rows_processed+MAX_SAMPLES_PER_2_PERIODS
        rows_to_process = datetime_index[n_rows_processed:end_index]
        indicies_for_period = np.where(rows_to_process < period.end_time)[0]
        if indicies_for_period.size > 0:
            first_i_for_period = indicies_for_period[0] + n_rows_processed
            last_i_for_period = indicies_for_period[-1] + n_rows_processed + 1
            boundaries[period] = (first_i_for_period, last_i_for_period)
            n_rows_processed += last_i_for_period - first_i_for_period

    return periods, boundaries
