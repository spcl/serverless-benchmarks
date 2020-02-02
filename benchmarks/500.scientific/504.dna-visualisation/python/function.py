import datetime
import os
import numpy as np
from itertools import islice

from . import storage
client = storage.storage.get_instance()

def handler(event):

    input_bucket = event.get('bucket').get('input')
    key = event.get('object').get('key')
    download_path = '/tmp/{}'.format(key)

    download_begin = datetime.datetime.now()
    client.download(input_bucket, key, download_path)
    download_stop = datetime.datetime.now()

    data = open(download_path, "r").read()

    process_begin = datetime.datetime.now()
    result = transform(data)
    process_end = datetime.datetime.now()

    download_time = (download_stop - download_begin) / datetime.timedelta(microseconds=1)
    process_time = (process_end - process_begin) / datetime.timedelta(microseconds=1)

    return {
            'result': result,
            'measurement': {
                'download_time': download_time,
                'compute_time': process_time
            }
    }

def _k_mers(sequence, k):
    it = iter(sequence)
    result = tuple(islice(it, k))
    if len(result) == k:
        yield "".join(result)
    for elem in it:
        result = result[1:] + (elem,)
        yield "".join(result)

def transform(sequence, method="squiggle"):
    '''Transforms a DNA sequence into a series of coordinates for 2D visualization.

    Args:
        sequence (str): The DNA sequence to transform.
        method (str): The method by which to transform the sequence. Defaults to "squiggle". Valid options are ``squiggle``, ``gates``, ``yau``, ``randic`` and ``qi``.
        bar (bool): Whether to display a progress bar. Defaults to false.

    Returns:
        tuple: A tuple containing two lists: one for the x coordinates and one for the y coordinates.

    Example:
        >>> transform("ATGC")
        ([0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0], [0, 0.5, 0, -0.5, -1, -0.5, 0, -0.5, 0])
        >>> transform("ATGC", method="gates")
        ([0, 0, 0, 1, 0], [0, -1, 0, 0, 0])
        >>> transform("ATGC", method="yau")
        ([0, 0.5, 1.0, 1.8660254037844386, 2.732050807568877], [0, -0.8660254037844386, 0.0, -0.5, 0.0])
        >>> transform("ATGC", method="yau-bp")
        ([0, 1, 2, 3, 4], [0, -1, 0, -0.5, 0.0])
        >>> transform("ATGC", method="randic")
        ([0, 1, 2, 3], [3, 2, 1, 0])
        >>> transform("ATGC", method="qi")
        ([0, 1, 2], [8, 7, 11])

    Warning:
        The entire sequence must be able to fit in memory.

    Raises:
        ValueError: When an invalid character is in the sequence.
    '''

    sequence = sequence.upper()

    if method == "squiggle":
        running_value = 0
        x, y = np.linspace(0, len(sequence), 2 * len(sequence) + 1), [0]
        for character in sequence:
            if character == "A":
                y.extend([running_value + 0.5, running_value])
            elif character == "C":
                y.extend([running_value - 0.5, running_value])
            elif character == "T":
                y.extend([running_value - 0.5, running_value - 1])
                running_value -= 1
            elif character == "G":
                y.extend([running_value + 0.5, running_value + 1])
                running_value += 1
            else:
                y.extend([running_value] * 2)
        return list(x), y

    elif method == "gates":
        x, y = [0], [0]
        for character in sequence:
            if character == "A":
                x.append(x[-1]) # no change in x coord
                y.append(y[-1] - 1)
            elif character == "T":
                x.append(x[-1]) # no change in x coord
                y.append(y[-1] + 1)
            elif character == "G":
                x.append(x[-1] + 1)
                y.append(y[-1]) # no change in y coord
            elif character == "C":
                x.append(x[-1] - 1)
                y.append(y[-1]) # no change in y coord
            else:
                raise ValueError("Invalid character in sequence: " + character + ". Gates's method does not support non-ATGC bases. Try using method=squiggle.")

    elif method == "yau":
        x, y = [0], [0]
        for character in sequence:
            if character == "A":
                x.append(x[-1] + 0.5)
                y.append(y[-1] - ((3**0.5) / 2))
            elif character == "T":
                x.append(x[-1] + 0.5)
                y.append(y[-1] + ((3**0.5) / 2))
            elif character == "G":
                x.append(x[-1] + ((3**0.5) / 2))
                y.append(y[-1] - 0.5)
            elif character == "C":
                x.append(x[-1] + ((3**0.5) / 2))
                y.append(y[-1] + 0.5)
            else:
                raise ValueError("Invalid character in sequence: " + character + ". Yau's method does not support non-ATGC bases. Try using method=squiggle.")

    elif method == "yau-bp":
        x, y = [0], [0]
        for character in sequence:
            if character == "A":
                x.append(x[-1] + 1)
                y.append(y[-1] - 1)
            elif character == "T":
                x.append(x[-1] + 1)
                y.append(y[-1] + 1)
            elif character == "G":
                x.append(x[-1] + 1)
                y.append(y[-1] - 0.5)
            elif character == "C":
                x.append(x[-1] + 1)
                y.append(y[-1] + 0.5)
            else:
                raise ValueError("Invalid character in sequence: " + character + ". Yau's method does not support non-ATGC bases. Try using method=squiggle.")

    elif method == "randic":
        x, y = [], []
        mapping = dict(A=3, T=2, G=1, C=0)
        for i, character in enumerate(sequence):
            x.append(i)
            try:
                y.append(mapping[character])
            except KeyError:
                raise ValueError("Invalid character in sequence: " + character + ". Randić's method does not support non-ATGC bases. Try using method=squiggle.")

    elif method == "qi":
        mapping = {'AA': 12,
                   'AC': 4,
                   'GT': 6,
                   'AG': 0,
                   'CC': 13,
                   'CA': 5,
                   'CG': 10,
                   'TT': 15,
                   'GG': 14,
                   'GC': 11,
                   'AT': 8,
                   'GA': 1,
                   'TG': 7,
                   'TA': 9,
                   'TC': 3,
                   'CT': 2}
        x, y = [], []

        for i, k_mer in enumerate(_k_mers(sequence, 2)):
            x.append(i)
            try:
                y.append(mapping[k_mer])
            except KeyError:
                raise ValueError("Invalid k-mer in sequence: " + k_mer + ". Qi's method does not support non-ATGC bases. Try using method=squiggle.")

    else:
        raise ValueError("Invalid method. Valid methods are 'squiggle', 'gates', 'yau', and 'randic'.")

    return x, y
