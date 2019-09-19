#!/usr/bin/env python
"""
    LookUpService gets all information and prepares MRML schema.
    TODO: Append switch information;

Copyright 2017 California Institute of Technology
   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at
       http://www.apache.org/licenses/LICENSE-2.0
   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
Title 			: dtnrm
Author			: Justas Balcas
Email 			: justas.balcas (at) cern.ch
@Copyright		: Copyright (C) 2016 California Institute of Technology
Date			: 2017/09/26
"""
import sys
import os
import time
import tempfile
import datetime
import importlib
import pprint
import ConfigParser
from rdflib import Graph
from rdflib import URIRef, Literal
from rdflib.compare import isomorphic
from DTNRMLibs.MainUtilities import getLogger
from DTNRMLibs.MainUtilities import getStreamLogger
from DTNRMLibs.MainUtilities import getConfig
from DTNRMLibs.MainUtilities import evaldict
from DTNRMLibs.MainUtilities import createDirs
from DTNRMLibs.MainUtilities import generateHash
from DTNRMLibs.FECalls import getAllHosts
from DTNRMLibs.FECalls import getDBConn
from DTNRMLibs.MainUtilities import getVal

class prefixDB(object):
    """ This generates all known default prefixes """
    def __init__(self, config, sitename):
        self.config = config
        self.sitename = sitename
        self.prefixes = {}
        self.getSavedPrefixes()

    def getSavedPrefixes(self):
        """Get Saved prefixes from a configuration file"""
        prefixes = {}
        for key in ['mrs', 'nml', 'owl', 'rdf', 'xml', 'xsd', 'rdfs', 'schema']:
            prefixes[key] = self.config.get('prefixes', key)
        prefixSite = "%s:%s:%s" % (self.config.get('prefixes', 'site'),
                                   self.config.get(self.sitename, 'domain'),
                                   self.config.get(self.sitename, 'year'))
        prefixes['site'] = prefixSite
        self.prefixes = prefixes

    def genUriRef(self, prefix, add=None, custom=None):
        """ Generate URIRef and return """
        if custom:
            return URIRef(custom)
        if not add:
            return URIRef("%s" % self.prefixes[prefix])
        return URIRef("%s%s" % (self.prefixes[prefix], add))

    def genLiteral(self, value):
        """ Returns simple Literal RDF out """
        return Literal(value)


class LookUpService(object):
    """ Lookup Service """
    def __init__(self, config, logger, sitename):
        self.sitename = sitename
        self.logger = logger
        self.config = config
        self.prefixDB = prefixDB(config, sitename)
        self.dbI = getDBConn()
        self.newGraph = None

    def addToGraph(self, sub, pred, obj):
        """ Add to graph new info. Input:
            sub (list) max len 2
            pred (list) max len 2
            obj (list) max len 2 if 1 will use Literal value
        """
        if len(obj) == 1 and len(sub) == 1:
            self.newGraph.add((self.prefixDB.genUriRef(sub[0]),
                               self.prefixDB.genUriRef(pred[0], pred[1]),
                               self.prefixDB.genLiteral(obj[0])))
        elif len(obj) == 1 and len(sub) == 2:
            self.newGraph.add((self.prefixDB.genUriRef(sub[0], sub[1]),
                               self.prefixDB.genUriRef(pred[0], pred[1]),
                               self.prefixDB.genLiteral(obj[0])))
        elif len(obj) == 2 and len(sub) == 1:
            self.newGraph.add((self.prefixDB.genUriRef(sub[0]),
                               self.prefixDB.genUriRef(pred[0], pred[1]),
                               self.prefixDB.genUriRef(obj[0], obj[1])))
        elif len(obj) == 2 and len(sub) == 2:
            self.newGraph.add((self.prefixDB.genUriRef(sub[0], sub[1]),
                               self.prefixDB.genUriRef(pred[0], pred[1]),
                               self.prefixDB.genUriRef(obj[0], obj[1])))
        else:
            raise Exception('Failing to add object to graph due to mismatch')

    def addIntfInfo(self, inputDict, prefixuri, main=True):
        """ This will add all information about interface """
        # '2' is for ipv4 information
        # Also can be added bytes_received, bytes_sent, dropin, dropout
        # errin, errout, packets_recv, packets_sent
        mappings = {}
        if main:
            mappings = {'2': ['address', 'MTU', 'UP', 'broadcast', 'txqueuelen',
                              'duplex', 'netmask', 'speed'],
                        '10': ['address', 'broadcast', 'netmask'],
                        '17': ['address', 'broadcast', 'netmask', 'mac-address']}
        else:
            mappings = {'2': ['address', 'MTU', 'UP', 'broadcast', 'bytes_received',
                              'bytes_sent', 'dropin', 'dropout', 'duplex',
                              'errin', 'errout', 'netmask', 'packets_recv',
                              'packets_sent', 'speed', 'txqueuelen'],
                        '10': ['address', 'broadcast', 'netmask'],
                        '17': ['address', 'broadcast', 'netmask', 'mac-address']}
        for dKey, dMappings in mappings.items():
            for mapping in dMappings:
                if dKey not in inputDict.keys():
                    continue
                if mapping in inputDict[dKey].keys() and inputDict[dKey][mapping]:
                    mName = mapping
                    value = inputDict[dKey][mapping]
                    if dKey == '10':
                        mName = 'ipv6-%s' % mapping
                    elif dKey == '17':
                        mName = 't17-%s' % mapping
                    if dKey == '2' and mapping == 'address':
                        mName = 'ipv4-address'
                        value = inputDict[dKey][mapping].split('/')[0]
                    self.addToGraph(['site', prefixuri],
                                    ['mrs', 'hasNetworkAddress'],
                                    ['site', '%s:%s' % (prefixuri, mName)])
                    self.addToGraph(['site', '%s:%s' % (prefixuri, mName)],
                                    ['rdf', 'type'],
                                    ['mrs', 'NetworkAddress'])
                    self.addToGraph(['site', "%s:%s" % (prefixuri, mName)],
                                    ['mrs', 'type'],
                                    [mapping])
                    self.addToGraph(['site', "%s:%s" % (prefixuri, mName)],
                                    ['mrs', 'value'],
                                    [value])

    def _deltaReduction(self, dbObj, delta, mainGraphName):
        delta['content'] = evaldict(delta['content'])
        self.logger.info('Working on %s delta reduction in state' % delta['uid'])
        mainGraph = Graph()
        mainGraph.parse(mainGraphName, format='turtle')
        reduction = delta['content']['reduction']
        tmpFile = tempfile.NamedTemporaryFile(delete=False)
        tmpFile.write(reduction)
        tmpFile.close()
        tmpGraph = Graph()
        tmpGraph.parse(tmpFile.name, format='turtle')
        os.unlink(tmpFile.name)
        self.logger.info('Main Graph len: %s Reduction Len: %s', len(mainGraph), len(tmpGraph))
        mainGraph -= tmpGraph
        dbObj.update('deltasmod', [{'uid': delta['uid'], 'updatedate': int(time.time()), 'modadd': 'removed'}])
        return mainGraph

    def _deltaAddition(self, dbObj, delta, mainGraphName):
        delta['content'] = evaldict(delta['content'])
        self.logger.info('Working on %s delta addition in state' % delta['uid'])
        mainGraph = Graph()
        mainGraph.parse(mainGraphName, format='turtle')
        addition = delta['content']['addition']
        tmpFile = tempfile.NamedTemporaryFile(delete=False)
        tmpFile.write(addition)
        tmpFile.close()
        tmpGraph = Graph()
        tmpGraph.parse(tmpFile.name, format='turtle')
        os.unlink(tmpFile.name)
        self.logger.info('Main Graph len: %s Addition Len: %s', len(mainGraph), len(tmpGraph))
        mainGraph += tmpGraph
        dbObj.update('deltasmod', [{'uid': delta['uid'], 'updatedate': int(time.time()), 'modadd': 'added'}])
        return mainGraph


    def appendDeltas(self, dbObj, mainGraphName):
        """ Append all deltas to Model """
        for modstate in ['add', 'added', 'remove']:
            for delta in dbObj.get('deltas', search=[['modadd', modstate]], limit=10):
                writeFile = False
                if delta['deltat'] == 'reduction':
                    if delta['state'] == 'failed':
                        continue
                    if delta['modadd'] in ['add', 'added', 'remove']:
                        mainGraph = self._deltaReduction(dbObj, delta, mainGraphName)
                        writeFile = True
                elif delta['deltat'] == 'addition':
                    if delta['modadd'] == 'add':
                        mainGraph = self._deltaAddition(dbObj, delta, mainGraphName)
                        writeFile = True
                    if delta['modadd'] == 'remove':
                        mainGraph = self._deltaReduction(dbObj, delta, mainGraphName)
                        writeFile = True
                if writeFile:
                    with open(mainGraphName, "w") as fd:
                        fd.write(mainGraph.serialize(format='turtle'))

    def checkForModelDiff(self, dbObj, saveName):
        # Check new model with current model inside DB.
        currentModel = dbObj.get('models', orderby=['insertdate', 'DESC'], limit=1)
        currentGraph = Graph()
        if currentModel:
            try:
                currentGraph.parse(currentModel[0]['fileloc'], format='turtle')
            except IOError:
                currentGraph = Graph()
            newGraph = Graph()
            newGraph.parse(saveName, format='turtle')
            return isomorphic(currentGraph, newGraph), currentModel
        return False, currentModel

    def startwork(self):
        """Main start """
        self.logger.info('Started LookupService work')
        dbObj = getVal(self.dbI, **{'sitename': self.sitename})
        workDir = self.config.get(self.sitename, 'privatedir') + "/LookUpService/"
        createDirs(workDir)
        currentModel = dbObj.get('models', orderby=['insertdate', 'DESC'], limit=1)
        self.newGraph = Graph()
        if currentModel:
            try:
                self.newGraph.parse(currentModel[0]['fileloc'], format='turtle')
            except IOError:
                self.newGraph = Graph()
        jOut = getAllHosts(self.sitename, self.logger)
        # Get switch information...
        switchPlugin = self.config.get(self.sitename, 'plugin')
        self.logger.info('Will load %s switch plugin' % switchPlugin)
        method = importlib.import_module("SiteFE.LookUpService.Plugins.%s" % switchPlugin.lower())
        switchInfo = method.getinfo(self.config, self.logger, jOut, self.sitename)
        # ====================================
        # Define all prefixes
        for prefix, val in self.prefixDB.prefixes.items():
            print prefix, val
            self.newGraph.bind(prefix, val)
        now = datetime.datetime.now()
        saveDir = "%s/%s" % (self.config.get(self.sitename, "privatedir"), "LookUpService")
        createDirs(saveDir)
        saveName = "%s/%s-%s-%s:%s:%s:%s.mrml" % (saveDir, now.year, now.month,
                                                  now.day, now.hour, now.minute, now.second)
        # {"ID": {}, "State": {}, "LastModel": {"UpdateTime": 0, "ModelID": "", "FileLoc": ""}}
        # Add main Topology
        #self.addToGraph(['site'],
        #                ['rdf', 'type'],
        #                ['nml', 'Topology'])
        self.newGraph.add((self.prefixDB.genUriRef('site'),
                           self.prefixDB.genUriRef('rdf', 'type'),
                           self.prefixDB.genUriRef('nml', 'Topology')))
        # self.addToGraph(['site'], ['rdf', 'type'], ['nml', "Topology"])
        # Add Service
        self.newGraph.add((self.prefixDB.genUriRef('site'),
                           self.prefixDB.genUriRef('nml', 'hasService'),
                           self.prefixDB.genUriRef('site', ':service+vsw')))
        self.newGraph.add((self.prefixDB.genUriRef('site', ':service+vsw'),
                           self.prefixDB.genUriRef('rdf', 'type'),
                           self.prefixDB.genUriRef('nml', 'SwitchingService')))

#        if 'l3_routing' in switchInfo.keys():
#            self.newGraph.add((self.prefixDB.genUriRef('site'),
#                               self.prefixDB.genUriRef('nml', 'hasService'),
#                               self.prefixDB.genUriRef('site', ':service+rst')))
#            self.newGraph.add((self.prefixDB.genUriRef('site', ':service+rst'),
#                               self.prefixDB.genUriRef('rdf', 'type'),
#                               self.prefixDB.genUriRef('mrs', 'RoutingTable')))
#            for switch, routingTable in switchInfo['l3_routing'].items():
#                for tablegress in['table+defaultIngress', 'table+defaultEgress']:
#                    routingtable = ":%s:%s" % (switch, tablegress)
#                    self.newGraph.add((self.prefixDB.genUriRef('site', ':%s:service+rst' % switch),
#                                       self.prefixDB.genUriRef('mrs', 'providesRoutingTable'),
#                                       self.prefixDB.genUriRef('site', routingtable)))
#                    self.newGraph.add((self.prefixDB.genUriRef('site', routingtable),
#                                       self.prefixDB.genUriRef('rdf', 'type'),
#                                       self.prefixDB.genUriRef('mrs', 'RoutingTable')))
#                    for vlan, address in routingTable.items():
#                        routename = routingtable + ":route+%s_%s" % (vlan, address['range'])
#                    self.newGraph.add((self.prefixDB.genUriRef('site', routename),
#                                       self.prefixDB.genUriRef('rdf', 'type'),
#                                       self.prefixDB.genUriRef('mrs', 'Route')))
#                    self.newGraph.add((self.prefixDB.genUriRef('site', routingtable),
#                                       self.prefixDB.genUriRef('mrs', 'hasRoute'),
#                                       self.prefixDB.genUriRef('site', routename)))
#                    if 'RTA_GATEWAY' in routeinfo.keys():
#                        self.newGraph.add((self.prefixDB.genUriRef('site', routename),
#                                           self.prefixDB.genUriRef('mrs', 'routeTo'),
#                                           self.prefixDB.genUriRef('site', '%s:%s' % (routename, 'to'))))
#                        self.newGraph.add((self.prefixDB.genUriRef('site', routename),
#                                           self.prefixDB.genUriRef('mrs', 'nextHop'),
#                                           self.prefixDB.genUriRef('site', '%s:%s' % (routename, 'black-hole'))))
#                        for vals in [['to', 'ipv4-prefix-list', '0.0.0.0/0'], ['black-hole', 'routing-policy', 'drop'], ['local', 'routing-policy', 'local']]:
#                            self.addToGraph(['site', '%s:%s' % (routename, vals[0])],
#                                            ['rdf', 'type'],
#                                            ['mrs', 'NetworkAddress'])
#                            self.addToGraph(['site', '%s:%s' % (routename, vals[0])],
#                                            ['mrs', 'type'],
#                                           [vals[1]])
#                            self.addToGraph(['site', '%s:%s' % (routename, vals[0])],
#                                            ['mrs', 'value'],
#                                            [vals[2]])





        # Add lableSwapping flag
        labelswap = "false"
        try:
            labelswap = self.config.get(self.sitename, 'labelswapping')
        except ConfigParser.NoOptionError:
            self.logger.info('Labelswapping parameter is not defined. By default it is set to False.')
        self.newGraph.add((self.prefixDB.genUriRef('site', ':service+vsw'),
                           self.prefixDB.genUriRef('nml', 'labelSwapping'),
                           self.prefixDB.genLiteral(labelswap)))
        # Add base encoding for service
        self.newGraph.add((self.prefixDB.genUriRef('site', ':service+vsw'),
                           self.prefixDB.genUriRef('nml', 'encoding'),
                           self.prefixDB.genUriRef('schema')))
        hosts = {}
        for _nodeName, nodeDict in jOut.items():
            # Define node
            self.newGraph.add((self.prefixDB.genUriRef('site'),
                               self.prefixDB.genUriRef('nml', 'hasNode'),
                               self.prefixDB.genUriRef('site', ":%s" % nodeDict['hostname'])))
            hosts[nodeDict['hostname']] = []
            # Node General description
            self.newGraph.add((self.prefixDB.genUriRef('site', ":%s" % nodeDict['hostname']),
                               self.prefixDB.genUriRef('nml', 'name'),
                               self.prefixDB.genLiteral(nodeDict['hostname'])))
            self.newGraph.add((self.prefixDB.genUriRef('site', ":%s" % nodeDict['hostname']),
                               self.prefixDB.genUriRef('rdf', 'type'),
                               self.prefixDB.genUriRef('nml', 'Node')))
            self.newGraph.add((self.prefixDB.genUriRef('site', ":%s" % nodeDict['hostname']),
                               self.prefixDB.genUriRef('nml', 'insertTime'),
                               self.prefixDB.genLiteral(nodeDict['insertdate'])))
            # Provide location information about site Frontend
            hostinfo = evaldict(nodeDict['hostinfo'])
            try:
                lat = self.config.get(self.sitename, 'latitude')
                lon = self.config.get(self.sitename, 'longitude')
                self.newGraph.add((self.prefixDB.genUriRef('site', ":%s" % nodeDict['hostname']),
                                   self.prefixDB.genUriRef('nml', 'latitude'),
                                   self.prefixDB.genLiteral(lat)))
                self.newGraph.add((self.prefixDB.genUriRef('site', ":%s" % nodeDict['hostname']),
                                   self.prefixDB.genUriRef('nml', 'longitude'),
                                   self.prefixDB.genLiteral(lon)))
            except ConfigParser.NoOptionError:
                self.logger.debug('Either one or both (latitude,longitude) are not defined. Continuing as normal')
            # Define Routing Service information

            self.newGraph.add((self.prefixDB.genUriRef('site', ":%s" % nodeDict['hostname']),
                               self.prefixDB.genUriRef('nml', 'hasService'),
                               self.prefixDB.genUriRef('site', ':%s:service+rst' % nodeDict['hostname'])))
            self.newGraph.add((self.prefixDB.genUriRef('site', ':%s:service+rst' % nodeDict['hostname']),
                               self.prefixDB.genUriRef('rdf', 'type'),
                               self.prefixDB.genUriRef('mrs', 'RoutingService')))

            for tablegress in['table+defaultIngress', 'table+defaultEgress']:
                routingtable = ":%s:%s" % (nodeDict['hostname'], tablegress)
                print routingtable 
                self.newGraph.add((self.prefixDB.genUriRef('site', ':%s:service+rst' % nodeDict['hostname']),
                                   self.prefixDB.genUriRef('mrs', 'providesRoutingTable'),
                                   self.prefixDB.genUriRef('site', routingtable)))
                self.newGraph.add((self.prefixDB.genUriRef('site', routingtable),
                                   self.prefixDB.genUriRef('rdf', 'type'),
                                   self.prefixDB.genUriRef('mrs', 'RoutingTable')))

                for routeinfo in hostinfo['NetInfo']["routes"]:
                    routename = ""
                    if 'RTA_GATEWAY' in routeinfo.keys():
                        routename = routingtable + ":route+default"
                    else:
                        routename = routingtable + ":route+%s_%s" % (routeinfo['RTA_PREFSRC'], routeinfo['dst_len'])
                    self.newGraph.add((self.prefixDB.genUriRef('site', routename),
                                       self.prefixDB.genUriRef('rdf', 'type'),
                                       self.prefixDB.genUriRef('mrs', 'Route')))
                    self.newGraph.add((self.prefixDB.genUriRef('site', routingtable),
                                       self.prefixDB.genUriRef('mrs', 'hasRoute'),
                                       self.prefixDB.genUriRef('site', routename)))
                    if 'RTA_GATEWAY' in routeinfo.keys():
                        self.newGraph.add((self.prefixDB.genUriRef('site', routename),
                                           self.prefixDB.genUriRef('mrs', 'routeTo'),
                                           self.prefixDB.genUriRef('site', '%s:%s' % (routename, 'to'))))
                        self.newGraph.add((self.prefixDB.genUriRef('site', routename),
                                           self.prefixDB.genUriRef('mrs', 'nextHop'),
                                           self.prefixDB.genUriRef('site', '%s:%s' % (routename, 'black-hole'))))
                        for vals in [['to', 'ipv4-prefix-list', '0.0.0.0/0'], ['black-hole', 'routing-policy', 'drop'], ['local', 'routing-policy', 'local']]:
                            self.addToGraph(['site', '%s:%s' % (routename, vals[0])],
                                            ['rdf', 'type'],
                                            ['mrs', 'NetworkAddress'])
                            self.addToGraph(['site', '%s:%s' % (routename, vals[0])],
                                            ['mrs', 'type'],
                                           [vals[1]])
                            self.addToGraph(['site', '%s:%s' % (routename, vals[0])],
                                            ['mrs', 'value'],
                                            [vals[2]])

                    else:
                        defaultroutename = routingtable + ":route+default:local"
                        self.newGraph.add((self.prefixDB.genUriRef('site', routename),
                                           self.prefixDB.genUriRef('mrs', 'routeTo'),
                                           self.prefixDB.genUriRef('site', '%s:%s' % (routename, 'to'))))
                        self.newGraph.add((self.prefixDB.genUriRef('site', routename),
                                           self.prefixDB.genUriRef('mrs', 'nextHop'),
                                           self.prefixDB.genUriRef('site', defaultroutename)))
                        self.addToGraph(['site', '%s:%s' % (routename, 'to')],
                                        ['rdf', 'type'],
                                        ['mrs', 'NetworkAddress'])
                        self.addToGraph(['site', '%s:%s' % (routename, 'to')],
                                        ['mrs', 'type'],
                                        ['ipv4-prefix-list'])
                        self.addToGraph(['site', '%s:%s' % (routename, 'to')],
                                        ['mrs', 'value'],
                                        ['%s/%s' % (routeinfo['RTA_DST'], routeinfo['dst_len'])])


            #for routeinfo in hostinfo['NetInfo']["routes"]:
            #    for tablegress in['table+defaultIngress', 'table+defaultEgress']:
            #        self.newGraph.add((self.prefixDB.genUriRef('site', ":%s:%s" % (nodeDict['hostname'], tablegress)),
            #                           self.prefixDB.genUriRef('mrs', 'RoutingTable'),
            #                           self.prefixDB.genUriRef('site', ":%s:%s" % (nodeDict['hostname'], tablegress))))
            # Add network interfaces for that specific node
            for intfKey, intfDict in hostinfo['NetInfo']["interfaces"].items():
                # We exclude QoS interfaces from adding them to MRML.
                # Even so, I still want to have this inside DB for debugging purposes
                if intfKey.endswith('-ifb'):
                    continue
                pprint.pprint(intfDict)
                switchName = 'unknown'
                switchPort = 'unknown'
                if 'switch' in intfDict.keys():
                    switchName = intfDict['switch']
                if 'switch_port' in intfDict.keys():
                    switchPort = intfDict['switch_port']
                if switchName == 'unknown' or 'switchPort' == 'unknown':
                    self.logger.info('Ignore %s interface as it does not have switch defined.' % intfKey)
                    continue
                hosts[nodeDict['hostname']].append({'switchName': switchName, 'switchPort': switchPort, 'intfKey': intfKey})
                newuri = ":%s:%s:%s:%s" % (switchName, switchPort, nodeDict['hostname'], intfKey)
                # Create new host definition
                self.newGraph.add((self.prefixDB.genUriRef('site', ":%s" % nodeDict['hostname']),
                                   self.prefixDB.genUriRef('nml', 'hasBidirectionalPort'),
                                   self.prefixDB.genUriRef('site', newuri)))
                # Specific node information.
                self.newGraph.add((self.prefixDB.genUriRef('site', newuri),
                                   self.prefixDB.genUriRef('rdf', 'type'),
                                   self.prefixDB.genUriRef('nml', 'BidirectionalPort')))
                # Add floating ip pool list for interface from the agent
                # ==========================================================================================
                if 'ipv4-floatingip-pool' in intfDict.keys():
                    self.addToGraph(['site', newuri],
                                    ['mrs', 'hasNetworkAddress'],
                                    ['site', "%s:%s" % (newuri, 'ipv4-floatingip-pool')])
                    self.addToGraph(['site', "%s:%s" % (newuri, 'ipv4-floatingip-pool')],
                                    ['rdf', 'type'],
                                    ['mrs', 'NetworkAddress'])
                    self.addToGraph(['site', "%s:%s" % (newuri, 'ipv4-floatingip-pool')],
                                    ['mrs', 'type'],
                                    ["ipv4-floatingip-pool"])
                    self.addToGraph(['site', "%s:%s" % (newuri, 'ipv4-floatingip-pool')],
                                    ['mrs', 'value'],
                                    [str(intfDict["ipv4-floatingip-pool"])])
                # Add vlan range for interface from the agent
                # ==========================================================================================
                if 'vlan_range' in intfDict.keys():
                    self.newGraph.add((self.prefixDB.genUriRef('site', newuri),
                                       self.prefixDB.genUriRef('nml', 'hasService'),
                                       self.prefixDB.genUriRef('site', "%s:%s" % (newuri, 'bandwidthService'))))
                    self.newGraph.add((self.prefixDB.genUriRef('site', newuri),
                                       self.prefixDB.genUriRef('nml', 'isAlias'),
                                       self.prefixDB.genUriRef('site', ":%s:%s:+" % (switchName, switchPort))))
                    # BANDWIDTH Service for INTERFACE
                    # ==========================================================================================
                    bws = "%s:%s" % (newuri, 'bandwidthService')
                    self.newGraph.add((self.prefixDB.genUriRef('site', bws),
                                       self.prefixDB.genUriRef('rdf', 'type'),
                                       self.prefixDB.genUriRef('mrs', 'BandwidthService')))
                    self.newGraph.add((self.prefixDB.genUriRef('site', bws),
                                       self.prefixDB.genUriRef('mrs', 'type'),
                                       self.prefixDB.genLiteral('guaranteedCapped')))

                    for item in [['unit', 'unit', "mbps"],
                                 ['max_bandwidth', 'maximumCapacity', 10000000000],
                                 ['available_bandwidth', 'availableCapacity', 10000000000],
                                 ['granularity', 'granularity', 1000000],
                                 ['reservable_bandwidth', 'reservableCapacity', 10000000000],
                                 ['min_bandwidth', 'minReservableCapacity', 10000000000]]:
                        value = item[2]
                        if item[0] in intfDict.keys():
                            value = intfDict[item[0]]
                        try:
                            value = int(int(value) / 1000000)
                        except ValueError:
                            value = str(value)
                        self.newGraph.add((self.prefixDB.genUriRef('site', bws),
                                           self.prefixDB.genUriRef('mrs', item[1]),
                                           self.prefixDB.genLiteral(value)))
                    # ==========================================================================================
                if 'capacity' in intfDict.keys():
                    self.newGraph.add((self.prefixDB.genUriRef('site', newuri),
                                       self.prefixDB.genUriRef('mrs', 'capacity'),
                                       self.prefixDB.genLiteral(intfDict['capacity'])))
                if 'vlan_range' in intfDict.keys():
                    self.newGraph.add((self.prefixDB.genUriRef('site', newuri),
                                       self.prefixDB.genUriRef('nml', 'hasLabelGroup'),
                                       self.prefixDB.genUriRef('site', "%s:vlan-range" % newuri)))
                    self.newGraph.add((self.prefixDB.genUriRef('site', "%s:vlan-range" % newuri),
                                       self.prefixDB.genUriRef('rdf', 'type'),
                                       self.prefixDB.genUriRef('nml', 'LabelGroup')))
                    self.newGraph.add((self.prefixDB.genUriRef('site', "%s:vlan-range" % newuri),
                                       self.prefixDB.genUriRef('nml', 'labeltype'),
                                       self.prefixDB.genUriRef('schema', '#vlan')))
                    self.newGraph.add((self.prefixDB.genUriRef('site', "%s:vlan-range" % newuri),
                                       self.prefixDB.genUriRef('nml', 'values'),
                                       self.prefixDB.genLiteral(intfDict['vlan_range'])))
                shared = False
                if 'shared' in intfDict.keys():
                    shared = 'notshared'
                    if intfDict['shared']:
                        shared = 'shared'
                    self.newGraph.add((self.prefixDB.genUriRef('site', newuri),
                                       self.prefixDB.genUriRef('mrs', 'type'),
                                       self.prefixDB.genLiteral(shared)))
                # Now lets also list all interface information to MRML
                self.addIntfInfo(intfDict, newuri)
                # List each VLAN:
                if 'desttype' not in intfDict.keys():
                    continue
                if intfDict['desttype'] != 'server':
                    continue
                if 'vlans' in intfDict.keys():
                    for vlanName, vlanDict in intfDict['vlans'].items():
                        # We exclude QoS interfaces from adding them to MRML.
                        # Even so, I still want to have this inside DB for debugging purposes
                        if vlanName.endswith('-ifb'):
                            continue
                        if not isinstance(vlanDict, dict):
                            pprint.pprint(vlanDict)
                            continue
                        # '2' is for ipv4 information
                        vlanuri = ":%s:%s:%s:%s" % (switchName, switchPort, nodeDict['hostname'], vlanName)
                        self.newGraph.add((self.prefixDB.genUriRef('site', vlanuri),
                                           self.prefixDB.genUriRef('rdf', 'type'),
                                           self.prefixDB.genUriRef('nml', 'BidirectionalPort')))
                        self.newGraph.add((self.prefixDB.genUriRef('site', newuri),
                                           self.prefixDB.genUriRef('nml', 'hasService'),
                                           self.prefixDB.genUriRef('site', "%s:%s" % (newuri, 'bandwidthService'))))
                        if shared:
                            self.newGraph.add((self.prefixDB.genUriRef('site', vlanuri),
                                               self.prefixDB.genUriRef('mrs', 'type'),
                                               self.prefixDB.genLiteral(shared)))
                        self.newGraph.add((self.prefixDB.genUriRef('site', ":%s" % nodeDict['hostname']),
                                           self.prefixDB.genUriRef('nml', 'hasBidirectionalPort'),
                                           self.prefixDB.genUriRef('site', vlanuri)))
                        self.newGraph.add((self.prefixDB.genUriRef('site', newuri),
                                           self.prefixDB.genUriRef('nml', 'hasBidirectionalPort'),
                                           self.prefixDB.genUriRef('site', vlanuri)))
                        if 'vlanid' in vlanDict.keys():
                            self.newGraph.add((self.prefixDB.genUriRef('site', vlanuri),
                                               self.prefixDB.genUriRef('nml', 'hasLabel'),
                                               self.prefixDB.genUriRef('site', "%s:vlan" % vlanuri)))
                            self.newGraph.add((self.prefixDB.genUriRef('site', "%s:vlan" % vlanuri),
                                               self.prefixDB.genUriRef('rdf', 'type'),
                                               self.prefixDB.genUriRef('nml', 'Label')))
                            self.newGraph.add((self.prefixDB.genUriRef('site', "%s:vlan" % vlanuri),
                                               self.prefixDB.genUriRef('nml', 'labeltype'),
                                               self.prefixDB.genUriRef('schema', '#vlan')))
                            self.newGraph.add((self.prefixDB.genUriRef('site', "%s:vlan" % vlanuri),
                                               self.prefixDB.genUriRef('nml', 'value'),
                                               self.prefixDB.genLiteral(vlanDict['vlanid'])))
                        # Add hasNetworkAddress for vlan
                        # Now the mapping of the interface information:
                        self.addIntfInfo(vlanDict, vlanuri, False)
        # Add Switch information to MRML
        for switchName, switchDict in switchInfo['switches'].items():
            print switchName, switchDict
            for portName, portSwitch in switchDict.items():
                newuri = ":%s:%s:%s" % (switchName, portName, portSwitch)
                self.newGraph.add((self.prefixDB.genUriRef('site'),
                                   self.prefixDB.genUriRef('nml', 'hasBidirectionalPort'),
                                   self.prefixDB.genUriRef('site', newuri)))
                self.newGraph.add((self.prefixDB.genUriRef('site', ':service+vsw'),
                                   self.prefixDB.genUriRef('nml', 'hasBidirectionalPort'),
                                   self.prefixDB.genUriRef('site', newuri)))
                self.newGraph.add((self.prefixDB.genUriRef('site', newuri),
                                   self.prefixDB.genUriRef('rdf', 'type'),
                                   self.prefixDB.genUriRef('nml', 'BidirectionalPort')))
                if switchName in switchInfo['vlans'].keys():
                    if portName in switchInfo['vlans'][switchName].keys():
                        # Add information about bidirection switch port
                        if 'vlan_range' in switchInfo['vlans'][switchName][portName].keys() and switchInfo['vlans'][switchName][portName]['vlan_range']:
                            self.newGraph.add((self.prefixDB.genUriRef('site', newuri),
                                               self.prefixDB.genUriRef('nml', 'hasLabelGroup'),
                                               self.prefixDB.genUriRef('site', "%s:vlan-range" % newuri)))
                            self.newGraph.add((self.prefixDB.genUriRef('site', "%s:vlan-range" % newuri),
                                               self.prefixDB.genUriRef('rdf', 'type'),
                                               self.prefixDB.genUriRef('nml', 'LabelGroup')))
                            self.newGraph.add((self.prefixDB.genUriRef('site', "%s:vlan-range" % newuri),
                                               self.prefixDB.genUriRef('nml', 'labeltype'),
                                               self.prefixDB.genUriRef('schema', '#vlan')))
                            self.newGraph.add((self.prefixDB.genUriRef('site', "%s:vlan-range" % newuri),
                                               self.prefixDB.genUriRef('nml', 'values'),
                                               self.prefixDB.genLiteral(switchInfo['vlans'][switchName][portName]['vlan_range'])))
                        if 'capacity' in switchInfo['vlans'][switchName][portName].keys() and switchInfo['vlans'][switchName][portName]['capacity']:
                            self.newGraph.add((self.prefixDB.genUriRef('site', newuri),
                                               self.prefixDB.genUriRef('mrs', 'capacity'),
                                               self.prefixDB.genLiteral(switchInfo['vlans'][switchName][portName]['capacity'])))
                        if 'isAlias' in switchInfo['vlans'][switchName][portName].keys() and switchInfo['vlans'][switchName][portName]['isAlias']:
                            self.newGraph.add((self.prefixDB.genUriRef('site', newuri),
                                               self.prefixDB.genUriRef('nml', 'isAlias'),
                                               self.prefixDB.genUriRef('', custom=switchInfo['vlans'][switchName][portName]['isAlias'])))
                        else:
                            if portSwitch in hosts.keys():
                                for item in hosts[portSwitch]:
                                    if item['switchName'] == switchName:
                                        if item['switchPort'] == portName:
                                            suri = "%s:%s" % (newuri, item['intfKey'])
                                            self.newGraph.add((self.prefixDB.genUriRef('site', newuri),
                                                               self.prefixDB.genUriRef('nml', 'isAlias'),
                                                               self.prefixDB.genUriRef('site', suri)))
                    else:
                        self.logger.debug('Port %s is not in switchInfo' % portName)
                else:
                    self.logger.debug('switchName $%s is not in switchInfo' % switchName)

        with open(saveName, "w") as fd:
            fd.write(self.newGraph.serialize(format='turtle'))
        hashNum = generateHash(self.newGraph.serialize(format='turtle'))

        # Append all deltas to the model
        self.appendDeltas(dbObj, saveName)
        if dbObj.get('models', limit=1, search=[['uid', hashNum]]):
            raise Exception('hashNum %s is already in database...' % hashNum)

        self.logger.info('Checking if new model is different from previous')
        modelsEqual, modelinDB = self.checkForModelDiff(dbObj, saveName)
        lastKnownModel = {'uid': hashNum, 'insertdate': int(time.time()), 'fileloc': saveName}
        if modelsEqual:
            if modelinDB[0]['insertdate'] < int(time.time() - 3600):
                # Force to update model every hour, Even there is no update;
                self.logger.info('Forcefully update model in db as it is older than 1h')
                dbObj.insert('models', [lastKnownModel])
            else:
                self.logger.info('Models are equal.')
                lastKnownModel = modelinDB[0]
                os.unlink(saveName)
        else:
            self.logger.info('Models are different. Update DB')
            dbObj.insert('models', [lastKnownModel])
        self.logger.info('Last Known Model: %s' % str(lastKnownModel))

        # Clean Up old models (older than 24h.)
        for model in dbObj.get('models', limit=100, orderby=['insertdate', 'ASC']):
            if model['insertdate'] < int(time.time() - 86400):
                self.logger.info('delete %s', model)
                try:
                    os.unlink(model['fileloc'])
                except OSError as ex:
                    self.logger.debug('Got OS Error removing this model %s. Exc: %s' % (model, str(ex)))
                dbObj.delete('models', [['id', model['id']]])


def execute(config=None, logger=None):
    """Main Execute"""
    if not config:
        config = getConfig(["/etc/dtnrm-site-fe.conf"])
    if not logger:
        component = 'LookUpService'
        logger = getLogger("%s/%s/" % (config.get('general', 'logDir'), component), config.get(component, 'logLevel'))
    for siteName in config.get('general', 'sites').split(','):
        policer = LookUpService(config, logger, siteName)
        policer.startwork()


if __name__ == '__main__':
    print 'WARNING: ONLY FOR DEVELOPMENT!!!!. Number of arguments:', len(sys.argv), 'arguments.'
    print 'Argument List:', str(sys.argv)
    execute(logger=getStreamLogger())
