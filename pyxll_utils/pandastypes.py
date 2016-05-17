"""
Custom excel types for pandas objects (eg dataframes).

For information about custom types in PyXLL see:
https://www.pyxll.com/docs/udfs.html#custom-types

For information about pandas see:
http://pandas.pydata.org/

Including this module in your pyxll config adds the following custom types that can
be used as return and argument types to your pyxll functions:

	- dataframe
	- series
	- series_t

Dataframes with multi-index indexes or columns will be returned with the columns and
index values in the resulting array. For normal indexes, the index will only be
returned as part of the resulting array if the index is named.

eg::

	from pyxll import xl_func
	import pandas as pa

	@xl_func("int rows, int cols, float value: dataframe")
	def make_empty_dataframe(rows, cols, value):
		# create an empty dataframe
		df = pa.DataFrame({chr(c + ord('A')) : value for c in range(cols)}, index=range(rows))
		
		# return it. The custom type will convert this to a 2d array that
		# excel will understand when this function is called as an array
		# function.
		return df

    @xl_func("dataframe df, string col: float")
    def sum_column(df, col):
        return df[col].sum()

In excel (use Ctrl+Shift+Enter to enter an array formula)::

	=make_empty_dataframe(3, 3, 100)
	
	>>  A	B	C
	>> 100	100	100
	>> 100	100	100
	>> 100	100	100

    =sum_column(A1:C4, "A")

    >> 300
"""
import pytz
from pyxll import xl_return_type, xl_arg_type
import datetime as dt
import pandas as pa
import numpy as np

UTC = pytz.timezone('UTC')


@xl_return_type("dataframe", "var")
def _dataframe_to_var(df):
    """return a list of lists that excel can understand"""
    if not isinstance(df, pa.DataFrame):
        return df
    df = df.astype(np.float, False)
    df = df.applymap(lambda x: RuntimeError() if isinstance(x, float) and np.isnan(x) else x)
 
    index_header = [str(df.index.name)] if df.index.name is not None else []
    if isinstance(df.index, pa.MultiIndex):
        index_header = [str(x) or "" for x in df.index.names]

    if isinstance(df.columns, pa.MultiIndex):
        result = [([""] * len(index_header)) + list(z) for z in zip(*list(df.columns))]
        for header in result:
            for i in range(1, len(header) - 1):
                if header[-i] == header[-i-1]:
                    header[-i] = ""

        if index_header:
            column_names = [x or "" for x in df.columns.names]
            for i, col_name in enumerate(column_names):
                result[i][len(index_header)-1] = col_name
    
            if column_names[-1]:
                index_header[-1] += (" \ " if index_header[-1] else "") + str(column_names[-1])

            num_levels = len(df.columns.levels)
            result[num_levels-1][:len(index_header)] = index_header
    else:
        if df.columns.name is not None:
            if index_header:
                if df.columns.name != '':
                    index_header[-1] += (" \ " if index_header[-1] else "") + str(df.columns.name)
            result = [index_header + list(df.columns)]
        else:
            result = []

    if isinstance(df.index, pa.MultiIndex):
        prev_ix = None
        for ix, row in df.iterrows():
            header = list(ix)
            if prev_ix:
                header = [x if x != px else "" for (x, px) in zip(ix, prev_ix)]
            result.append(header + list(row))
            prev_ix = ix

    elif index_header:
        for ix, row in df.iterrows():
            result.append([ix] + list(row))
    else:
        for ix, row in df.iterrows():
            result.append(list(row))

    return result


@xl_return_type("series", "var")
def _series_to_var(s):
    """return a list of lists that excel can understand"""
    if not isinstance(s, pa.Series):
        return s

    # convert values to floats (hack for right now bc it is converting ints to strings for some reason)
    # TODO: figure out why it is converting ints to strings
    s = s.astype(np.float, False)

    # convert any errors to exceptions so they appear correctly in Excel
    s = s.apply(lambda x: RuntimeError() if isinstance(x, float) and np.isnan(x) else x)

    # add tzinfo to any dates
    s = s.apply(_fix_tzinfo)
    idx_names = s.index.name
    s.index = [_fix_tzinfo(x) for x in s.index]
    s.index.name = idx_names

    # only return index if index name is defined
    if s.index.name is not None:
        sr = list(map(list, s.iteritems()))
    else:
        sr = [[x] for i, x in s.iteritems()]
    return sr


@xl_return_type("series_t", "var")
def _series_to_var_transform(s):
    """return a list of lists that excel can understand"""
    if not isinstance(s, pa.Series):
        return s

    # convert values to floats (hack for right now bc it is converting ints to strings for some reason)
    # TODO: figure out why it is converting ints to strings
    s = s.astype(np.float, False)

    # convert any errors to exceptions so they appear correctly in Excel
    s = s.apply(lambda x: RuntimeError() if isinstance(x, float) and np.isnan(x) else x)

    # add tzinfo to any dates
    s = s.apply(_fix_tzinfo)
    idx_names = s.index.name
    s.index = [_fix_tzinfo(x) for x in s.index]
    s.index.name = idx_names

    # only return index if index name is defined
    if s.index.name is not None:
        sr = list(zip(*s.iteritems()))
    else:
        sr = [[x for i, x in s.iteritems()]]

    return sr


@xl_arg_type("dataframe", "var")
def _var_to_dataframe(x):
    """return a pandas DataFrame from a list of lists"""
    columns = x[0]
    rows = x[1:]
    return pa.DataFrame(list(rows), columns=columns)


@xl_arg_type("series", "var")
def _var_to_series(s):
    """return a pandas Series from a list of lists (arranged vertically)"""
    if not isinstance(s, (list, tuple)):
        raise TypeError("Expected a list of lists")

    keys, values = [], []
    for row in s:
        if not isinstance(row, (list, tuple)):
            raise TypeError("Expected a list of lists")

        if len(row) < 2:
            raise RuntimeError("Expected rows of length 2 to convert to a pandas Series")
        key, value = row[:2]
        # skip any empty rows
        if key is None and value is None:
            continue
        keys.append(key)
        values.append(value)

    return pa.Series(values, index=keys)


@xl_arg_type("series_t", "var")
def _var_to_series_t(s):
    """return a pandas Series from a list of lists (arranged horizontally)"""
    if not isinstance(s, (list, tuple)):
        raise TypeError("Expected a list of lists")

    keys, values = [], []
    for row in zip(*s):
        if not isinstance(row, (list, tuple)):
            raise TypeError("Expected a list of lists")

        if len(row) < 2:
            raise RuntimeError("Expected rows of length 2 to convert to a pandas Series")
        key, value = row[:2]
        # skip any empty rows
        if key is None and value is None:
            continue
        keys.append(key)
        values.append(value)

    return pa.Series(values, index=keys)


def _fix_tzinfo(x):
    """
    Add timezone information to any native datetimes.
    pythoncom will fail to convert datetimes to Windows dates without tzinfo.
    
    This is useful if using these functions to convert a dataframe to native
    python types for setting to a Range using COM. If only passing objects
    to/from python using PyXLL functions then this isn't necessary (but
    isn't harmful either).
    """
    if isinstance(x, dt.date) and not isinstance(x, dt.datetime):
        x = dt.datetime(year=x.year, month=x.month, day=x.day)
    if isinstance(x, dt.datetime) and x.tzinfo is None:
        x = x.replace(tzinfo=UTC)
    return x

