#!/usr/bin/env python3
"""Register the fixed HTTP/HTTPS ingress mappings with a UPnP router."""
from __future__ import annotations
import argparse, socket
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

SERVICE_TYPES=('urn:schemas-upnp-org:service:WANIPConnection:1','urn:schemas-upnp-org:service:WANPPPConnection:1')
def discover(timeout=3):
    message=b'M-SEARCH * HTTP/1.1\r\nHOST:239.255.255.250:1900\r\nMAN:"ssdp:discover"\r\nMX:2\r\nST:urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n\r\n'
    sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); sock.settimeout(timeout); sock.sendto(message,('239.255.255.250',1900))
    data,_=sock.recvfrom(65535)
    headers={line.split(':',1)[0].lower():line.split(':',1)[1].strip() for line in data.decode(errors='replace').split('\r\n') if ':' in line}
    return headers['location']
def control(location):
    root=ET.fromstring(urlopen(location,timeout=5).read())
    for service in root.iter():
        values={child.tag.rsplit('}',1)[-1]:child.text for child in service}
        if values.get('serviceType') in SERVICE_TYPES: return values['serviceType'],urljoin(location,values['controlURL'])
    raise RuntimeError('Router has no WAN port-mapping service')
def add(service,url,client,port):
    args={'NewRemoteHost':'','NewExternalPort':str(port),'NewProtocol':'TCP','NewInternalPort':str(port),'NewInternalClient':client,'NewEnabled':'1','NewPortMappingDescription':'UDA reverse proxy','NewLeaseDuration':'0'}
    body='<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body><u:AddPortMapping xmlns:u="'+service+'">'+''.join(f'<{k}>{v}</{k}>' for k,v in args.items())+'</u:AddPortMapping></s:Body></s:Envelope>'
    request=Request(url,data=body.encode(),headers={'Content-Type':'text/xml; charset="utf-8"','SOAPAction':f'"{service}#AddPortMapping"'})
    urlopen(request,timeout=8).read()
def main():
    p=argparse.ArgumentParser(); p.add_argument('--client',required=True); p.add_argument('--ports',nargs='+',type=int,default=[80,443]); args=p.parse_args()
    service,url=control(discover())
    for port in args.ports: add(service,url,args.client,port)
if __name__=='__main__': main()
