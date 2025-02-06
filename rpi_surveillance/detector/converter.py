import torch


def save_onnx(model, input_shape, output_path):
    model.eval()
    x = torch.randn(input_shape)
    torch.onnx.export(
        model, 
        x, 
        output_path, 
        export_params=True, 
        opset_version=11, 
        do_constant_folding=True, 
        input_names=['input'], 
        output_names=['output'], 
        dynamic_axes={'input': {0: 'batch_size'}, 'output': {0: 'batch_size'}}
    )
