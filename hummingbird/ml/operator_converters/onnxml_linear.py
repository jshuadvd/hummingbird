# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

"""
Converters for ONNX-ML linear models.
"""

import numpy as np
from onnxconverter_common.registration import register_converter

from ._linear_implementations import LinearModel


def convert_onnx_linear_model(operator, device=None, extra_config={}):
    """
    Converter for `ai.onnx.ml.LinearClassifier`.

    Args:
        operator: An operator wrapping a `ai.onnx.ml.LinearClassifier` model
        device: String defining the type of device the converted operator should be run on
        extra_config: Extra configuration used to select the best conversion strategy

    Returns:
        A PyTorch model
    """

    assert operator is not None

    operator = operator.raw_operator
    coefficients = intercepts = classes = multi_class = None
    is_linear_regression = False

    for attr in operator.origin.attribute:
        if attr.name == "coefficients":
            coefficients = np.array(attr.floats).astype("float32")
        elif attr.name == "intercepts":
            intercepts = np.array(attr.floats).astype("float32")
        elif attr.name == "classlabels_ints":
            classes = np.array(attr.ints)
        elif attr.name == "multi_class":
            if attr.i != 0:  # https://github.com/onnx/onnx/blob/master/docs/Operators-ml.md#ai.onnx.ml.LinearClassifier
                multi_class = "multinomial"

    if any(v is None for v in [coefficients, intercepts, classes]):
        print("coefficients{}, intercepts{},  classes{}".format(coefficients, intercepts, classes))
        raise RuntimeError("Error parsing LinearClassifier, found unexpected None")
    if multi_class is None:  # if 'multi_class' attr was not present
        multi_class = "none" if len(classes) < 3 else "ovr"
    if operator.op_type == "LinearRegressor":
        is_linear_regression = True

    # Now reshape the coefficients/intercepts
    if len(classes) == 2:
        # for the binary case, it seems there is a duplicate copy of everything with opposite +/- sign. This just takes the correct copy
        coefficients = np.array([[np.array(val).astype("float32")] for val in coefficients[len(coefficients) // 2 :]]).astype(
            "float32"
        )
        intercepts = np.array([[np.array(val).astype("float32")] for val in intercepts[len(intercepts) // 2 :]]).astype(
            "float32"
        )
    elif len(classes) > 2:
        # intercepts are OK in this case.

        # reshape coefficients into tuples
        tmp = coefficients.reshape(len(classes), (len(coefficients) // len(classes)))
        # then unzip the zipmap format
        coefficients = np.array(list(zip(*tmp)))
    else:
        raise RuntimeError("Error parsing LinearClassifier, length of classes {} unexpected:{}".format(len(classes), classes))
    return LinearModel(
        coefficients, intercepts, device, classes=classes, multi_class=multi_class, is_linear_regression=is_linear_regression
    )


register_converter("ONNXMLLinearClassifier", convert_onnx_linear_model)
