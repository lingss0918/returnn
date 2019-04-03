
"""
Common settings for linters, e.g. pycharm-inspect.py or pylint.py.
"""

# Proceed like this: Fix all warnings for some file, then remove it from this list.
# I removed already all files which really should not have warnings (mostly the TF backend + shared files).
ignore_count_for_files = {
  'ActivationFunctions.py',
  'BestPathDecoder.py',
  'BundleFile.py',
  'CTC.py',
  'CachedDataset.py',
  'CustomLSTMFunctions.py',
  'Device.py',
  'Engine.py',
  'EngineTask.py',
  'External.py',
  'Fsa.py',
  'FunctionLoader.py',
  'HDFDataset.py',
  'Inv.py',
  'MultiBatchBeam.py',
  'Network.py',
  'NetworkBaseLayer.py',
  'NetworkCNNLayer.py',
  'NetworkCopyUtils.py',
  'NetworkCtcLayer.py',
  'NetworkDescription.py',
  'NetworkHiddenLayer.py',
  'NetworkLayer.py',
  'NetworkLstmLayer.py',
  'NetworkOutputLayer.py',
  'NetworkRecurrentLayer.py',
  'NetworkStream.py',
  'NetworkTwoDLayer.py',
  'NormalizationData.py',
  'OpBLSTM.py',
  'OpInvAlign.py',
  'OpLSTM.py',
  'OpLSTMCell.py',
  'OpLSTMCustom.py',
  'OpLSTMRec.py',
  'OpNumpyAlign.py',
  'RawWavDataset.py',
  'RecurrentTransform.py',
  'Server.py',
  'StereoDataset.py',
  'TFNetworkNeuralTransducer.py',
  'TFNetworkSegModLayer.py',
  'TFNetworkSigProcLayer.py',
  'TaskSystem.py',
  'TaskSystem_example.py',
  'TheanoUtil.py',
  'TorchWrapper.py',
  'TwoStateBestPathDecoder.py',
  'TwoStateHMMOp.py',
  'Updater.py',
}
