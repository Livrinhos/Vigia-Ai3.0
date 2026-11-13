"""Diagnóstico local, sem webcam, SMTP, treino ou alteração dos pesos."""
import argparse
import importlib.metadata
import json
import platform
import subprocess
import sys
from pathlib import Path


def diagnose():
    result = dict(python=sys.version, executable=sys.executable, platform=platform.platform(), packages={})
    for package in ('torch','torchvision','ultralytics','mediapipe','numpy','opencv-python','psutil'):
        try:
            result['packages'][package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            result['packages'][package] = None
    try:
        r = subprocess.run(['nvidia-smi','--query-gpu=name,driver_version,memory.total,memory.used,utilization.gpu',
                            '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=5,
                            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        result['nvidia_smi'] = r.stdout.strip() if r.returncode == 0 else 'indisponível'
    except (OSError, subprocess.TimeoutExpired):
        result['nvidia_smi'] = None
    try:
        import torch
        result.update(torch_cuda=torch.version.cuda, cuda_available=torch.cuda.is_available(),
                      compiled_architectures=torch.cuda.get_arch_list())
        result['cuda_devices'] = []
        for i in range(torch.cuda.device_count()):
            p = torch.cuda.get_device_properties(i)
            device = dict(index=i, name=p.name, total_vram=p.total_memory, capability=[p.major,p.minor])
            try:
                x = torch.ones((32,32),device=f'cuda:{i}')
                device['fp32_smoke'] = bool((x @ x == 32).all().item())
                del x
            except Exception as error:
                device['fp32_error'] = str(error)
            result['cuda_devices'].append(device)
    except Exception as error:
        result['torch_error'] = str(error)
    try:
        import cv2
        result['opencv'] = dict(opencl_available=cv2.ocl.haveOpenCL(),opencl_active=cv2.ocl.useOpenCL(),
                                build=cv2.getBuildInformation())
    except ImportError:
        result['opencv'] = None
    result['intel_note'] = 'Nenhuma aceleração Intel habilitada. OpenCL disponível não prova uso no MediaPipe/YOLO ou ganho em webcam USB.'
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        raise FileExistsError('Saída já existe.')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(diagnose(),indent=2),encoding='utf-8')
    print(a.output)
