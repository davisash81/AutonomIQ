"""Site-local BAS adapters. Default is simulated. BACnet adapter is read-only in this release."""
from .config import get_settings

class SimulatedAdapter:
    async def health(self): return {'adapter':'simulated','connected':False,'mode':'simulation','note':'No live BAS connection.'}
    async def discover(self): return {'devices':[],'mode':'simulation'}
    async def read(self, address): raise RuntimeError('No live BAS reads are configured; simulated adapter has no live point data.')

class BacnetReadOnlyAdapter:
    async def health(self):
        return {'adapter':'bacnet-ip-read-only','configured':bool(get_settings().bacnet_local_ip),'connected':False,'mode':'read-only','note':'Connect/discovery must be validated on the isolated site network.'}
    async def discover(self):
        import BAC0
        s=get_settings()
        if not s.bacnet_local_ip: raise RuntimeError('Set BACNET_LOCAL_IP on the site-local gateway.')
        async with BAC0.start(ip=f"{s.bacnet_local_ip}/{s.bacnet_subnet_mask}") as bacnet:
            bacnet.discover()
            devices=await bacnet.devices
            return {'devices':[str(x) for x in devices],'mode':'read-only'}
    async def read(self,address):
        raise NotImplementedError('Point-level BACnet read requires a reviewed device/object mapping. This API intentionally has no write operation.')

def get_adapter():
    if get_settings().bas_adapter=='bacnet_read_only': return BacnetReadOnlyAdapter()
    return SimulatedAdapter()
