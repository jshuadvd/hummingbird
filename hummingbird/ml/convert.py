# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

"""
Hummingbird main (converters) API.
"""
from copy import deepcopy
import numpy as np

from onnxconverter_common.registration import get_converter
from onnxconverter_common.optimizer import LinkedNode, _topological_sort

from .exceptions import MissingBackend
from ._parse import parse_sklearn_api_model
from .supported import backend_map
from ._utils import torch_installed, lightgbm_installed, xgboost_installed, onnx_installed
from . import constants

# Invoke the registration of all our converters.
from . import operator_converters  # noqa


def _supported_backend_check(backend):
    """
    Function used to check whether the specified backend is supported or not.
    """
    if not backend.lower() in backend_map:
        raise MissingBackend("Backend: {}".format(backend))


def _to_sklearn(self, backend, test_input=None, extra_config={}):
    """
    Utility function used to call the *scikit-learn* converter.
    """
    _supported_backend_check(backend)

    return convert_sklearn(self, test_input, extra_config)


def _to_lightgbm(self, backend, test_input=None, extra_config={}):
    """
    Utility function used to call the *LightGBM* converter.
    """
    _supported_backend_check(backend)

    return convert_lightgbm(self, test_input, extra_config)


def _to_xgboost(self, backend, test_input, extra_config={}):
    """
    Utility function used to call the *XGboost* converter.
    """
    _supported_backend_check(backend)

    return convert_xgboost(self, test_input, extra_config)


def convert_sklearn(model, test_input=None, extra_config={}):
    """
    This function converts the specified [scikit-learn] model into its [PyTorch] counterpart.
    The supported operators can be found at `hummingbird._supported_operators`.
    [scikit-learn]: https://scikit-learn.org/
    [PyTorch]: https://pytorch.org/

    Args:
        model: A scikit-learn model
        test_input: some input data used to trace the model execution
        extra_config: Extra configurations to be used by the individual operator converters.
                      The set of supported extra configurations can be found at `hummingbird.ml.supported`

    Examples:
        >>> pytorch_model = convert_sklearn(sklearn_model)

    Returns:
        A model implemented in *PyTorch*, which is equivalent to the input *scikit-learn* model
    """
    assert model is not None
    assert torch_installed(), "To use Hummingbird you need to install torch."

    from .ir_converters.topology import convert as topology_converter

    # Parse scikit-learn model as our internal data structure (i.e., Topology)
    # We modify the scikit learn model during optimizations.
    model = deepcopy(model)
    topology = parse_sklearn_api_model(model)

    # Convert the Topology object into a PyTorch model.
    hb_model = topology_converter(topology, extra_config=extra_config)
    return hb_model


def convert_lightgbm(model, test_input=None, extra_config={}):
    """
    This function is used to generate a [PyTorch] model from a given input [LightGBM] model.
    [LightGBM]: https://lightgbm.readthedocs.io/
    [PyTorch]: https://pytorch.org/

    Args:
        model: A LightGBM model (trained using the scikit-learn API)
        test_input: Some input data that will be used to trace the model execution
        extra_config: Extra configurations to be used by the individual operator converters.
                      The set of supported extra configurations can be found at `hummingbird.ml.supported`

    Examples:
        >>> pytorch_model = convert_lightgbm(lgbm_model)

    Returns:
        A *PyTorch* model which is equivalent to the input *LightGBM* model
    """
    assert lightgbm_installed(), "To convert LightGBM models you need to instal LightGBM."

    return convert_sklearn(model, test_input, extra_config)


def convert_xgboost(model, test_input, extra_config={}):
    """
    This function is used to generate a [PyTorch] model from a given input [XGBoost] model.
    [PyTorch]: https://pytorch.org/
    [XGBoost]: https://xgboost.readthedocs.io/

    Args:
        model: A XGBoost model (trained using the scikit-learn API)
        test_input: Some input data used to trace the model execution
        extra_config: Extra configurations to be used by the individual operator converters.
                      The set of supported extra configurations can be found at `hummingbird.ml.supported`

    Examples:
        >>> pytorch_model = convert_xgboost(xgb_model, [], extra_config={"n_features":200})

    Returns:
        A *PyTorch* model which is equivalent to the input *XGBoost* model
    """
    assert xgboost_installed(), "To convert XGboost models you need to instal XGBoost."

    # XGBoostRegressor and Classifier have different APIs for extracting the number of features.
    # In the former case we need to infer them from the test_input.
    if constants.N_FEATURES not in extra_config:
        if "_features_count" in dir(model):
            extra_config[constants.N_FEATURES] = model._features_count
        elif test_input is not None:
            if type(test_input) is np.ndarray and len(test_input.shape) == 2:
                extra_config[constants.N_FEATURES] = test_input.shape[1]
            else:
                raise RuntimeError(
                    "XGBoost converter is not able to infer the number of input features.\
                        Apparently test_input is not an ndarray. \
                        Please fill an issue at https://github.com/microsoft/hummingbird/."
                )
        else:
            raise RuntimeError(
                "XGBoost converter is not able to infer the number of input features.\
                    Please pass some test_input to the converter."
            )
    return convert_sklearn(model, test_input, extra_config)


def convert_onnxml(
    model,
    output_model_name=None,
    initial_types=None,
    input_names=None,
    output_names=None,
    test_data=None,
    target_opset=9,
    extra_config={},
):
    """
    This function converts the specified [ONNX-ML] model into its [ONNX] counterpart.
    The supported operators can be found at `hummingbird.ml.supported`.
    [ONNX-ML]: https://scikit-learn.org/
    [ONNX]: https://pytorch.org/

    Args:
        model: A model containing ONNX-ML operators
        output_model_name: The name of the ONNX model returned as output
        initial_types: A python list where each element is a tuple of a input name and a `onnxmltools.convert.common.data_types`
        input_names: A python list containig input names. Should be a subset of the input variables in the input ONNX-ML model.
        output_names: A python list containing the output names expected from the translated model.
                      Should be a subset of the output variables in the input ONNX-ML model.
        test_data: Some input data used to trace the model execution
        target_opset: The opset to use for the generated ONNX model
        extra_config: Extra configurations to be used by the individual operator converters.
                      The set of supported extra configurations can be found at `hummingbird.ml.supported`

    Examples:
        >>> onnx_model = convert_onnxml(onnx_ml_model, initial_types=[('input', FloatTensorType([1, 20])])

    Returns:
        A model containing only *ONNX* operators. The mode is equivalent to the input *ONNX-ML* model
    """
    assert model is not None
    assert torch_installed(), "To use Hummingbird you need to install torch."
    assert onnx_installed(), "To use the onnxml converter you need to install onnx and onnxruntime."
    assert (
        test_data is not None or initial_types is not None
    ), "Cannot generate test input data. Either pass some input data or the initial_types"

    from .ir_converters.linked_node import convert as linked_node_converter

    # Parse an ONNX-ML model into our internal data structure (i.e., LinkedNode)
    input_names = input_names if input_names is not None else [in_.name for in_ in model.input]
    inputs = [in_ for in_ in model.input if in_.name in input_names]

    assert len(inputs) > 0, "Provided input name does not match with any model's input."
    assert len(inputs) == 1, "Hummingbird currently do not support models with more than 1 input."
    assert initial_types is None or len(initial_types) == 1, "len(initial_types) {} differs from len(inputs) {}.".format(
        len(initial_types), len(inputs)
    )

    if output_names is None:
        output_names = [] if model.output is None else [o_.name for o_ in model.output]

    if test_data is None:
        assert (
            not initial_types[0][1].shape is None
        ), "Cannot generate test input data. Initial_types do not contain shape information."
        assert len(initial_types[0][1].shape) == 2, "Hummingbird currently support only inputs with len(shape) == 2."

        from onnxmltools.convert.common.data_types import FloatTensorType, Int32TensorType

        test_data = np.random.rand(initial_types[0][1].shape[0], initial_types[0][1].shape[1])
        if type(initial_types[0][1]) is FloatTensorType:
            test_data = np.array(test_data, dtype=np.float32)
        elif type(initial_types[0][1]) is Int32TensorType:
            test_data = np.array(test_data, dtype=np.int32)
        else:
            raise RuntimeError(
                "Type {} not supported. Please fill an issue on https://github.com/microsoft/hummingbird/.".format(
                    type(initial_types[0][1])
                )
            )

    onnx_ir = LinkedNode.build_from_onnx(
        model.node, [], [in_.name for in_ in model.input], output_names, [init_ for init_ in model.initializer]
    )

    # Convert the input onnx_ir object into ONNX. The outcome is a model containing only ONNX operators.
    onnx_model = linked_node_converter(onnx_ir, inputs, model.initializer, output_names, test_data, extra_config)
    return onnx_model