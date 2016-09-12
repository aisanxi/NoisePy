# -*- coding: utf-8 -*-
"""
A python module for seismic data analysis based on ASDF database

:Methods:
    aftan analysis (use pyaftan or aftanf77)
    C3(Correlation of coda of Cross-Correlation) computation
    python wrapper for Barmin's surface wave tomography Code
    Automatic Receiver Function Analysis( Iterative Deconvolution and Harmonic Stripping )
    Eikonal Tomography
    Helmholtz Tomography 
    Stacking/Rotation for Cross-Correlation Results from SEED2CORpp
    Bayesian Monte Carlo Inversion of Surface Wave and Receiver Function datasets (To be added soon)

:Dependencies:
    numpy >=1.9.1
    scipy >=0.18.0
    matplotlib >=1.4.3
    ObsPy >=1.0.1
    pyfftw 0.10.3 (optional)
    
:Copyright:
    Author: Lili Feng
    Graduate Research Assistant
    CIEI, Department of Physics, University of Colorado Boulder
    email: lili.feng@colorado.edu
"""
import pyasdf
import numpy as np
import matplotlib.pyplot as plt
import obspy
import warnings
import copy
import os, shutil
import numba
from functools import partial
import multiprocessing
import pyaftan
from subprocess import call
from obspy.clients.fdsn.client import Client

sta_info_default={'rec_func': 0, 'xcorr': 1, 'isnet': 0}

xcorr_header_default={'netcode1': '', 'stacode1': '', 'netcode2': '', 'stacode2': '', 'chan1': '', 'chan2': '',
        'npts': 12345, 'b': 12345, 'e': 12345, 'delta': 12345, 'dist': 12345, 'az': 12345, 'baz': 12345, 'stackday': 0}

xcorr_sacheader_default = {'knetwk': '', 'kstnm': '', 'kcmpnm': '', 'stla': 12345, 'stlo': 12345, 
            'kuser0': '', 'kevnm': '', 'evla': 12345, 'evlo': 12345, 'evdp': 0., 'dist': 0., 'az': 12345, 'baz': 12345, 
                'delta': 12345, 'npts': 12345, 'user0': 0, 'b': 12345, 'e': 12345}

monthdict={1: 'JAN', 2: 'FEB', 3: 'MAR', 4: 'APR', 5: 'MAY', 6: 'JUN', 7: 'JUL', 8: 'AUG', 9: 'SEP', 10: 'OCT', 11: 'NOV', 12: 'DEC'}


class noiseASDF(pyasdf.ASDFDataSet):
    
    def init_working_env(self, datadir, workingdir):
        self.datadir    = datadir
        self.workingdir = workingdir
    
    def write_stationxml(self, staxml, source='CIEI'):
        inv=obspy.core.inventory.inventory.Inventory(networks=[], source=source)
        for staid in self.waveforms.list():
            inv+=self.waveforms[staid].StationXML
        inv.write(staxml, format='stationxml')
        return
    
    def write_stationtxt(self, stafile):
        """Write obspy inventory to txt station list(format used in SEED2COR)
        """
        try:
            auxiliary_info=self.auxiliary_data.StaInfo
            isStaInfo=True
        except:
            isStaInfo=False
        with open(stafile, 'w') as f:
            for staid in self.waveforms.list():
                stainv=self.waveforms[staid].StationXML
                netcode=stainv.networks[0].code
                stacode=stainv.networks[0].stations[0].code
                lon=stainv.networks[0].stations[0].longitude
                lat=stainv.networks[0].stations[0].latitude
                if isStaInfo:
                    staid_aux=netcode+'/'+stacode
                    ccflag=auxiliary_info[staid_aux].parameters['xcorr']
                    f.writelines('%s %3.4f %3.4f %d %s\n' %(stacode, lon, lat, ccflag, netcode) )
                else:
                    f.writelines('%s %3.4f %3.4f %s\n' %(stacode, lon, lat, netcode) )        
        return
    
    def read_stationtxt(self, stafile, source='CIEI', chans=['BHZ', 'BHE', 'BHN'], dnetcode='TA'):
        """Read txt station list 
        """
        sta_info=sta_info_default.copy()
        with open(stafile, 'r') as f:
            Sta=[]
            site=obspy.core.inventory.util.Site(name='01')
            creation_date=obspy.core.utcdatetime.UTCDateTime(0)
            inv=obspy.core.inventory.inventory.Inventory(networks=[], source=source)
            total_number_of_channels=len(chans)
            for lines in f.readlines():
                lines=lines.split()
                stacode=lines[0]
                lon=float(lines[1])
                lat=float(lines[2])
                netcode=dnetcode
                ccflag=None
                if len(lines)==5:
                    try:
                        ccflag=int(lines[3])
                        netcode=lines[4]
                    except ValueError:
                        ccflag=int(lines[4])
                        netcode=lines[3]
                if len(lines)==4:
                    try:
                        ccflag=int(lines[3])
                    except ValueError:
                        netcode=lines[3]
                netsta=netcode+'.'+stacode
                if Sta.__contains__(netsta):
                    index=Sta.index(netsta)
                    if abs(self[index].lon-lon) >0.01 and abs(self[index].lat-lat) >0.01:
                        raise ValueError('Incompatible Station Location:' + netsta+' in Station List!')
                    else:
                        print 'Warning: Repeated Station:' +netsta+' in Station List!'
                        continue
                channels=[]
                if lon>180.:
                    lon-=360.
                for chan in chans:
                    channel=obspy.core.inventory.channel.Channel(code=chan, location_code='01', latitude=lat, longitude=lon,
                            elevation=0.0, depth=0.0)
                    channels.append(channel)
                station=obspy.core.inventory.station.Station(code=stacode, latitude=lat, longitude=lon, elevation=0.0,
                        site=site, channels=channels, total_number_of_channels = total_number_of_channels, creation_date = creation_date)
                network=obspy.core.inventory.network.Network(code=netcode, stations=[station])
                networks=[network]
                inv+=obspy.core.inventory.inventory.Inventory(networks=networks, source=source)
                staid_aux=netcode+'/'+stacode
                if ccflag!=None:
                    sta_info['xcorr']=ccflag
                self.add_auxiliary_data(data=np.array([]), data_type='StaInfo', path=staid_aux, parameters=sta_info)
        print 'Writing obspy inventory to ASDF dataset'
        self.add_stationxml(inv)
        print 'End writing obspy inventory to ASDF dataset'
        return 
    
    def read_stationtxt_ind(self, stafile, source='CIEI', chans=['BHZ', 'BHE', 'BHN'], s_ind=1, lon_ind=2, lat_ind=3, n_ind=0):
        """Read txt station list, column index can be changed
        """
        sta_info=sta_info_default.copy()
        with open(stafile, 'r') as f:
            Sta=[]
            site=obspy.core.inventory.util.Site(name='01')
            creation_date=obspy.core.utcdatetime.UTCDateTime(0)
            inv=obspy.core.inventory.inventory.Inventory(networks=[], source=source)
            total_number_of_channels=len(chans)
            for lines in f.readlines():
                lines=lines.split()
                stacode=lines[s_ind]
                lon=float(lines[lon_ind])
                lat=float(lines[lat_ind])
                netcode=lines[n_ind]
                netsta=netcode+'.'+stacode
                if Sta.__contains__(netsta):
                    index=Sta.index(netsta)
                    if abs(self[index].lon-lon) >0.01 and abs(self[index].lat-lat) >0.01:
                        raise ValueError('Incompatible Station Location:' + netsta+' in Station List!')
                    else:
                        print 'Warning: Repeated Station:' +netsta+' in Station List!'
                        continue
                channels=[]
                if lon>180.:
                    lon-=360.
                for chan in chans:
                    channel=obspy.core.inventory.channel.Channel(code=chan, location_code='01', latitude=lat, longitude=lon,
                            elevation=0.0, depth=0.0)
                    channels.append(channel)
                station=obspy.core.inventory.station.Station(code=stacode, latitude=lat, longitude=lon, elevation=0.0,
                        site=site, channels=channels, total_number_of_channels = total_number_of_channels, creation_date = creation_date)
                network=obspy.core.inventory.network.Network(code=netcode, stations=[station])
                networks=[network]
                inv+=obspy.core.inventory.inventory.Inventory(networks=networks, source=source)
                staid_aux=netcode+'/'+stacode
                self.add_auxiliary_data(data=np.array([]), data_type='StaInfo', path=staid_aux, parameters=sta_info)
        print 'Writing obspy inventory to ASDF dataset'
        self.add_stationxml(inv)
        print 'End writing obspy inventory to ASDF dataset'
        return 
    
    def get_limits_lonlat(self):
        """Get the geographical limits of the stations
        """
        staLst=self.waveforms.list()
        minlat=90.
        maxlat=-90.
        minlon=360.
        maxlon=0.
        for staid in staLst:
            lat, elv, lon=self.waveforms[staid].coordinates.values()
            if lon<0: lon+=360.
            minlat=min(lat, minlat)
            maxlat=max(lat, maxlat)
            minlon=min(lon, minlon)
            maxlon=max(lon, maxlon)
        print 'latitude range: ', minlat, '-', maxlat, 'longitude range:', minlon, '-', maxlon
        return
            
    
    def wsac_xcorr(self, netcode1, stacode1, netcode2, stacode2, chan1, chan2, outdir='.', pfx='COR'):
        """Write cross-correlation data from ASDF to sac file
        ==============================================================================
        Input Parameters:
        netcode1, stacode1, chan1   - network/station/channel name for station 1
        netcode2, stacode2, chan2   - network/station/channel name for station 2
        outdir                      - output directory
        pfx                         - prefix
        Output:
        e.g. outdir/COR/TA.G12A/COR_TA.G12A_BHT_TA.R21A_BHT.SAC
        ==============================================================================
        """
        subdset=self.auxiliary_data.NoiseXcorr[netcode1][stacode1][netcode2][stacode2][chan1][chan2]
        sta1=self.waveforms[netcode1+'.'+stacode1].StationXML.networks[0].stations[0]
        sta2=self.waveforms[netcode2+'.'+stacode2].StationXML.networks[0].stations[0]
        xcorr_sacheader=xcorr_sacheader_default.copy()
        xcorr_sacheader['kuser0']=netcode1
        xcorr_sacheader['kevnm']=stacode1
        xcorr_sacheader['knetwk']=netcode2
        xcorr_sacheader['kstnm']=stacode2
        xcorr_sacheader['kcmpnm']=chan1+chan2
        xcorr_sacheader['evla']=sta1.latitude
        xcorr_sacheader['evlo']=sta1.longitude
        xcorr_sacheader['stla']=sta2.latitude
        xcorr_sacheader['stlo']=sta2.longitude
        xcorr_sacheader['dist']=subdset.parameters['dist']
        xcorr_sacheader['az']=subdset.parameters['az']
        xcorr_sacheader['baz']=subdset.parameters['baz']
        xcorr_sacheader['b']=subdset.parameters['b']
        xcorr_sacheader['e']=subdset.parameters['e']
        xcorr_sacheader['delta']=subdset.parameters['delta']
        xcorr_sacheader['npts']=subdset.parameters['npts']
        xcorr_sacheader['user0']=subdset.parameters['stackday']
        sacTr=obspy.io.sac.sactrace.SACTrace(data=subdset.data.value, **xcorr_sacheader)
        if not os.path.isdir(outdir+'/'+pfx+'/'+netcode1+'.'+stacode1):
            os.makedirs(outdir+'/'+pfx+'/'+netcode1+'.'+stacode1)
        sacfname=outdir+'/'+pfx+'/'+netcode1+'.'+stacode1+'/'+ \
                pfx+'_'+netcode1+'.'+stacode1+'_'+chan1+'_'+netcode2+'.'+stacode2+'_'+chan2+'.SAC'
        sacTr.write(sacfname)
        return
    
    def wsac_xcorr_all(self, netcode1, stacode1, netcode2, stacode2, outdir='.', pfx='COR'):
        """Write all components of cross-correlation data from ASDF to sac file
        ==============================================================================
        Input Parameters:
        netcode1, stacode1  - network/station name for station 1
        netcode2, stacode2  - network/station name for station 2
        outdir              - output directory
        pfx                 - prefix
        Output:
        e.g. outdir/COR/TA.G12A/COR_TA.G12A_BHT_TA.R21A_BHT.SAC
        ==============================================================================
        """
        subdset=self.auxiliary_data.NoiseXcorr[netcode1][stacode1][netcode2][stacode2]
        channels1=subdset.list()
        channels2=subdset[channels1[0]].list()
        for chan1 in channels1:
            for chan2 in channels2:
                self.wsac_xcorr(netcode1=netcode1, stacode1=stacode1, netcode2=netcode2,
                    stacode2=stacode2, chan1=chan1, chan2=chan2, outdir=outdir, pfx=pfx)
        return
    
    def get_xcorr_trace(self, netcode1, stacode1, netcode2, stacode2, chan1, chan2):
        subdset=self.auxiliary_data.NoiseXcorr[netcode1][stacode1][netcode2][stacode2][chan1][chan2]
        evla, evz, evlo=self.waveforms[netcode1+'.'+stacode1].coordinates.values()
        stla, stz, stlo=self.waveforms[netcode2+'.'+stacode2].coordinates.values()
        tr=obspy.core.Trace()
        tr.data=subdset.data.value
        tr.stats.sac={}
        tr.stats.sac.evla=evla
        tr.stats.sac.evlo=evlo
        tr.stats.sac.stla=stla
        tr.stats.sac.stlo=stlo
        tr.stats.sac.kuser0=netcode1
        tr.stats.sac.kevnm=stacode1
        tr.stats.network=netcode2
        tr.stats.station=stacode2
        tr.stats.sac.kcmpnm=chan1+chan2
        tr.stats.sac.dist=subdset.parameters['dist']
        tr.stats.sac.az=subdset.parameters['az']
        tr.stats.sac.baz=subdset.parameters['baz']
        tr.stats.sac.b=subdset.parameters['b']
        tr.stats.sac.e=subdset.parameters['e']
        tr.stats.sac.user0=subdset.parameters['stackday']
        tr.stats.delta=subdset.parameters['delta']
        return tr
        
    def read_xcorr(self, datadir, pfx='COR', fnametype=2, inchannels=None, verbose=True):
        """Read cross-correlation data in ASDF database
        ===========================================================================================================
        Input Parameters:
        datadir                 - data directory
        pfx                     - prefix
        inchannels              - input channels, if None, will read channel information from obspy inventory
        fnametype               - input sac file name type
                                    =1: datadir/COR/G12A/COR_G12A_BHZ_R21A_BHZ.SAC
                                    =2: datadir/COR/G12A/COR_G12A_R21A.SAC
        -----------------------------------------------------------------------------------------------------------
        Output:
        ASDF path           : self.auxiliary_data.NoiseXcorr[netcode1][stacode1][netcode2][stacode2][chan1][chan2]
        ===========================================================================================================
        """
        staLst=self.waveforms.list()
        # main loop for station pairs
        if inchannels!=None:
            try:
                if not isinstance(inchannels[0], obspy.core.inventory.channel.Channel):
                    channels=[]
                    for inchan in inchannels:
                        channels.append(obspy.core.inventory.channel.Channel(code=inchan, location_code='01',
                                        latitude=0, longitude=0, elevation=0, depth=0) )
                else:
                    channels=inchannels
            except:
                inchannels=None
        for staid1 in staLst:
            for staid2 in staLst:
                netcode1, stacode1=staid1.split('.')
                netcode2, stacode2=staid2.split('.')
                if staid1 >= staid2:
                    continue
                if fnametype==2 and not os.path.isfile(datadir+'/'+pfx+'/'+staid1+'/'+pfx+'_'+staid1+'_'+staid2+'.SAC'):
                    continue
                if inchannels==None:
                    channels1=self.waveforms[staid1].StationXML.networks[0].stations[0].channels
                    channels2=self.waveforms[staid2].StationXML.networks[0].stations[0].channels
                else:
                    channels1=channels
                    channels2=channels
                skipflag=False
                for chan1 in channels1:
                    if skipflag:
                        break
                    for chan2 in channels2:
                        if fnametype==1:
                            fname=datadir+'/'+pfx+'/'+staid1+'/'+pfx+'_'+staid1+'_'+chan1.code+'_'+staid2+'_'+chan2.code+'.SAC'
                        elif fnametype==2:
                            fname=datadir+'/'+pfx+'/'+staid1+'/'+pfx+'_'+staid1+'_'+staid2+'.SAC'
                        try:
                            tr=obspy.core.read(fname)[0]
                        except IOError:
                            skipflag=True
                            break
                        # write cross-correlation header information
                        xcorr_header=xcorr_header_default.copy()
                        xcorr_header['b']=tr.stats.sac.b
                        xcorr_header['e']=tr.stats.sac.e
                        xcorr_header['netcode1']=netcode1
                        xcorr_header['netcode2']=netcode2
                        xcorr_header['stacode1']=stacode1
                        xcorr_header['stacode2']=stacode2
                        xcorr_header['npts']=tr.stats.npts
                        xcorr_header['delta']=tr.stats.delta
                        xcorr_header['stackday']=tr.stats.sac.user0
                        try:
                            xcorr_header['dist']=tr.stats.sac.dist
                            xcorr_header['az']=tr.stats.sac.az
                            xcorr_header['baz']=tr.stats.sac.baz
                        except AttributeError:
                            lon1=self.waveforms[staid1].StationXML.networks[0].stations[0].longitude
                            lat1=self.waveforms[staid1].StationXML.networks[0].stations[0].latitude
                            lon2=self.waveforms[staid2].StationXML.networks[0].stations[0].longitude
                            lat2=self.waveforms[staid2].StationXML.networks[0].stations[0].latitude
                            dist, az, baz=obspy.geodetics.gps2dist_azimuth(lat1, lon1, lat2, lon2)
                            dist=dist/1000.
                            xcorr_header['dist']=dist
                            xcorr_header['az']=az
                            xcorr_header['baz']=baz
                        staid_aux=netcode1+'/'+stacode1+'/'+netcode2+'/'+stacode2
                        xcorr_header['chan1']=chan1.code
                        xcorr_header['chan2']=chan2.code
                        self.add_auxiliary_data(data=tr.data, data_type='NoiseXcorr', path=staid_aux+'/'+chan1.code+'/'+chan2.code, parameters=xcorr_header)
                if verbose and not skipflag:
                    print 'reading xcorr data: '+netcode1+'.'+stacode1+'_'+netcode2+'.'+stacode2
        return
        
    
    def xcorr_stack(self, datadir, startyear, startmonth, endyear, endmonth, pfx='COR', outdir=None, inchannels=None, fnametype=1):
        """Stack cross-correlation data from monthly-stacked sac files
        ===========================================================================================================
        Input Parameters:
        datadir                 - data directory
        startyear, startmonth   - start date for stacking
        endyear, endmonth       - end date for stacking
        pfx                     - prefix
        outdir                  - output directory (None is not to save sac files)
        inchannels              - input channels, if None, will read channel information from obspy inventory
        fnametype               - input sac file name type
                                    =1: datadir/COR/G12A/COR_G12A_BHZ_R21A_BHZ.SAC
                                    =2: datadir/COR/G12A/COR_G12A_R21A.SAC
        -----------------------------------------------------------------------------------------------------------
        Output:
        ASDF path           : self.auxiliary_data.NoiseXcorr[netcode1][stacode1][netcode2][stacode2][chan1][chan2]
        sac file(optional)  : outdir/COR/TA.G12A/COR_TA.G12A_BHT_TA.R21A_BHT.SAC
        ===========================================================================================================
        """
        # prepare year/month list for stacking
        utcdate=obspy.core.utcdatetime.UTCDateTime(startyear, startmonth, 1)
        ylst=np.array([], dtype=int)
        mlst=np.array([], dtype=int)
        while (utcdate.year<endyear or (utcdate.year<=endyear and utcdate.month<=endmonth) ):
            ylst=np.append(ylst, utcdate.year)
            mlst=np.append(mlst, utcdate.month)
            try:
                utcdate.month+=1
            except ValueError:
                utcdate.year+=1
                utcdate.month=1
        mnumb=mlst.size
        # determine channels if inchannels is specified
        if inchannels!=None:
            try:
                if not isinstance(inchannels[0], obspy.core.inventory.channel.Channel):
                    channels=[]
                    for inchan in inchannels:
                        channels.append(obspy.core.inventory.channel.Channel(code=inchan, location_code='01',
                                        latitude=0, longitude=0, elevation=0, depth=0) )
                else:
                    channels=inchannels
            except:
                inchannels=None
        if inchannels==None:
            fnametype==1
        else:
            if len(channels)!=1:
                fnametype==1
        staLst=self.waveforms.list()
        # main loop for station pairs
        for staid1 in staLst:
            for staid2 in staLst:
                netcode1, stacode1=staid1.split('.')
                netcode2, stacode2=staid2.split('.')
                if stacode1 >= stacode2:
                    continue
                stackedST=[]
                cST=[]
                initflag=True
                if inchannels==None:
                    channels1=self.waveforms[staid1].StationXML.networks[0].stations[0].channels
                    channels2=self.waveforms[staid2].StationXML.networks[0].stations[0].channels
                else:
                    channels1=channels
                    channels2=channels
                for im in xrange(mnumb):
                    skipflag=False
                    for chan1 in channels1:
                        if skipflag:
                            break
                        for chan2 in channels2:
                            month=monthdict[mlst[im]]
                            yrmonth=str(ylst[im])+'.'+month
                            if fnametype==1:
                                fname=datadir+'/'+yrmonth+'/'+pfx+'/'+stacode1+'/'+pfx+'_'+stacode1+'_'+chan1.code+'_'+stacode2+'_'+chan2.code+'.SAC'
                            elif fnametype==2:
                                fname=datadir+'/'+yrmonth+'/'+pfx+'/'+stacode1+'/'+pfx+'_'+stacode1+'_'+stacode2+'.SAC'
                            if not os.path.isfile(fname):
                                skipflag=True
                                break
                            try:
                                tr=obspy.core.read(fname)[0]
                            except TypeError:
                                warnings.warn('Unable to read SAC for: ' + stacode1 +'_'+stacode2 +' Month: '+yrmonth, UserWarning, stacklevel=1)
                                skipflag=True
                            if np.isnan(tr.data).any() or abs(tr.data.max())>1e20:
                                warnings.warn('NaN monthly SAC for: ' + stacode1 +'_'+stacode2 +' Month: '+yrmonth, UserWarning, stacklevel=1)
                                skipflag=True
                                break
                            cST.append(tr)
                    if len(cST)!=len(channels1)*len(channels2) or skipflag:
                        cST=[]
                        continue
                    if initflag:
                        stackedST=copy.deepcopy(cST)
                        initflag=False
                    else:
                        for itr in xrange(len(cST)):
                            mtr=cST[itr]
                            stackedST[itr].data+=mtr.data
                            stackedST[itr].stats.sac.user0+=mtr.stats.sac.user0
                    cST=[]
                if len(stackedST)==len(channels1)*len(channels2):
                    print 'Finished Stacking for:'+netcode1+'.'+stacode1+'_'+netcode2+'.'+stacode2
                    # create sac output directory 
                    if outdir!=None:
                        if not os.path.isdir(outdir+'/'+pfx+'/'+netcode1+'.'+stacode1):
                            os.makedirs(outdir+'/'+pfx+'/'+netcode1+'.'+stacode1)
                    # write cross-correlation header information
                    xcorr_header=xcorr_header_default.copy()
                    xcorr_header['b']=stackedST[0].stats.sac.b
                    xcorr_header['e']=stackedST[0].stats.sac.e
                    xcorr_header['netcode1']=netcode1
                    xcorr_header['netcode2']=netcode2
                    xcorr_header['stacode1']=stacode1
                    xcorr_header['stacode2']=stacode2
                    xcorr_header['npts']=stackedST[0].stats.npts
                    xcorr_header['delta']=stackedST[0].stats.delta
                    xcorr_header['stackday']=stackedST[0].stats.sac.user0
                    try:
                        xcorr_header['dist']=stackedST[0].stats.sac.dist
                        xcorr_header['az']=stackedST[0].stats.sac.az
                        xcorr_header['baz']=stackedST[0].stats.sac.baz
                    except AttributeError:
                        lon1=self.waveforms[staid1].StationXML.networks[0].stations[0].longitude
                        lat1=self.waveforms[staid1].StationXML.networks[0].stations[0].latitude
                        lon2=self.waveforms[staid2].StationXML.networks[0].stations[0].longitude
                        lat2=self.waveforms[staid2].StationXML.networks[0].stations[0].latitude
                        dist, az, baz=obspy.geodetics.gps2dist_azimuth(lat1, lon1, lat2, lon2)
                        dist=dist/1000.
                        xcorr_header['dist']=dist
                        xcorr_header['az']=az
                        xcorr_header['baz']=baz
                    staid_aux=netcode1+'/'+stacode1+'/'+netcode2+'/'+stacode2
                    i=0
                    for chan1 in channels1:
                        for chan2 in channels2:
                            stackedTr=stackedST[i]
                            if outdir!=None:
                                outfname=outdir+'/'+pfx+'/'+netcode1+'.'+stacode1+'/'+ \
                                    pfx+'_'+netcode1+'.'+stacode1+'_'+chan1.code+'_'+netcode2+'.'+stacode2+'_'+chan2.code+'.SAC'
                                stackedTr.write(outfname,format='SAC')
                            xcorr_header['chan1']=chan1.code
                            xcorr_header['chan2']=chan2.code
                            self.add_auxiliary_data(data=stackedTr.data, data_type='NoiseXcorr', path=staid_aux+'/'+chan1.code+'/'+chan2.code, parameters=xcorr_header)
                            i+=1
        return
    
    def xcorr_stack_mp(self, datadir, outdir, startyear, startmonth, endyear, endmonth,
                    pfx='COR', inchannels=None, fnametype=1, subsize=1000, deletesac=True, nprocess=None):
        """Stack cross-correlation data from monthly-stacked sac files with multiprocessing
        ===========================================================================================================
        Input Parameters:
        datadir                 - data directory
        outdir                  - output directory 
        startyear, startmonth   - start date for stacking
        endyear, endmonth       - end date for stacking
        pfx                     - prefix
        inchannels              - input channels, if None, will read channel information from obspy inventory
        fnametype               - input sac file name type
                                    =1: datadir/COR/G12A/COR_G12A_BHZ_R21A_BHZ.SAC
                                    =2: datadir/COR/G12A/COR_G12A_R21A.SAC
        subsize                 - subsize of processing list, use to prevent lock in multiprocessing process
        deletesac               - delete output sac files
        nprocess                - number of processes
        -----------------------------------------------------------------------------------------------------------
        Output:
        ASDF path           : self.auxiliary_data.NoiseXcorr[netcode1][stacode1][netcode2][stacode2][chan1][chan2]
        sac file(optional)  : outdir/COR/TA.G12A/COR_TA.G12A_BHT_TA.R21A_BHT.SAC
        ===========================================================================================================
        """
        utcdate=obspy.core.utcdatetime.UTCDateTime(startyear, startmonth, 1)
        ylst=np.array([], dtype=int)
        mlst=np.array([], dtype=int)
        print 'Preparing data for stacking'
        while (utcdate.year<endyear or (utcdate.year<=endyear and utcdate.month<=endmonth) ):
            ylst=np.append(ylst, utcdate.year)
            mlst=np.append(mlst, utcdate.month)
            try:
                utcdate.month+=1
            except ValueError:
                utcdate.year+=1
                utcdate.month=1
        mnumb=mlst.size
        staLst=self.waveforms.list()
        if inchannels!=None:
            try:
                if not isinstance(inchannels[0], obspy.core.inventory.channel.Channel):
                    channels=[]
                    for inchan in inchannels:
                        channels.append(obspy.core.inventory.channel.Channel(code=inchan, location_code='01',
                                        latitude=0, longitude=0, elevation=0, depth=0) )
                else:
                    channels=inchannels
            except:
                inchannels=None
        if inchannels==None:
            fnametype==1
        else:
            if len(channels)!=1:
                fnametype==1
        stapairInvLst=[]
        for staid1 in staLst:
            if not os.path.isdir(outdir+'/'+pfx+'/'+staid1):
                os.makedirs(outdir+'/'+pfx+'/'+staid1)
            for staid2 in staLst:
                netcode1, stacode1=staid1.split('.')
                netcode2, stacode2=staid2.split('.')
                if stacode1 >= stacode2:
                    continue
                inv = self.waveforms[staid1].StationXML + self.waveforms[staid2].StationXML
                if inchannels!=None:
                    inv.networks[0].stations[0].channels=channels
                    inv.networks[1].stations[0].channels=channels
                stapairInvLst.append(inv) 
        print 'Start multiprocessing stacking !'
        if len(stapairInvLst) > subsize:
            Nsub = int(len(stapairInvLst)/subsize)
            for isub in xrange(Nsub):
                print isub,'in',Nsub
                cstapairs=stapairInvLst[isub*subsize:(isub+1)*subsize]
                STACKING = partial(stack4mp, datadir=datadir, outdir=outdir, ylst=ylst, mlst=mlst, pfx=pfx, fnametype=fnametype)
                pool = multiprocessing.Pool(processes=nprocess)
                pool.map(STACKING, cstapairs) #make our results with a map call
                pool.close() #we are not adding any more processes
                pool.join() #tell it to wait until all threads are done before going on
            cstapairs=stapairInvLst[(isub+1)*subsize:]
            STACKING = partial(stack4mp, datadir=datadir, outdir=outdir, ylst=ylst, mlst=mlst, pfx=pfx, fnametype=fnametype)
            pool = multiprocessing.Pool(processes=nprocess)
            pool.map(STACKING, cstapairs) 
            pool.close() 
            pool.join() 
        else:
            STACKING = partial(stack4mp, datadir=datadir, outdir=outdir, ylst=ylst, mlst=mlst, pfx=pfx, fnametype=fnametype)
            pool = multiprocessing.Pool(processes=nprocess)
            pool.map(STACKING, stapairInvLst) 
            pool.close() 
            pool.join() 
        print 'End of multiprocessing stacking !'
        print 'Reading data into ASDF database'
        for inv in stapairInvLst:
            channels1=inv.networks[0].stations[0].channels
            netcode1=inv.networks[0].code
            stacode1=inv.networks[0].stations[0].code
            channels2=inv.networks[1].stations[0].channels
            netcode2=inv.networks[1].code
            stacode2=inv.networks[1].stations[0].code
            skipflag=False
            xcorr_header=xcorr_header_default.copy()
            xcorr_header['netcode1']=netcode1
            xcorr_header['netcode2']=netcode2
            xcorr_header['stacode1']=stacode1
            xcorr_header['stacode2']=stacode2
            staid_aux=netcode1+'/'+stacode1+'/'+netcode2+'/'+stacode2
            for chan1 in channels1:
                if skipflag:
                    break
                for chan2 in channels2:
                    sacfname=outdir+'/'+pfx+'/'+netcode1+'.'+stacode1+'/'+ \
                        pfx+'_'+netcode1+'.'+stacode1+'_'+chan1.code+'_'+netcode2+'.'+stacode2+'_'+chan2.code+'.SAC'
                    try:
                        tr=obspy.read(sacfname)[0]
                        # cross-correlation header 
                        xcorr_header['b']=tr.stats.sac.b
                        xcorr_header['e']=tr.stats.sac.e
                        xcorr_header['npts']=tr.stats.npts
                        xcorr_header['delta']=tr.stats.delta
                        xcorr_header['stackday']=tr.stats.sac.user0
                        try:
                            xcorr_header['dist']=tr.stats.sac.dist
                            xcorr_header['az']=tr.stats.sac.az
                            xcorr_header['baz']=tr.stats.sac.baz
                        except AttributeError:
                            lon1=inv.networks[0].stations[0].longitude
                            lat1=inv.networks[0].stations[0].latitude
                            lon2=inv.networks[1].stations[0].longitude
                            lat2=inv.networks[1].stations[0].latitude
                            dist, az, baz=obspy.geodetics.gps2dist_azimuth(lat1, lon1, lat2, lon2)
                            dist=dist/1000.
                            xcorr_header['dist']=dist
                            xcorr_header['az']=az
                            xcorr_header['baz']=baz
                        xcorr_header['chan1']=chan1.code
                        xcorr_header['chan2']=chan2.code
                        self.add_auxiliary_data(data=tr.data, data_type='NoiseXcorr', path=staid_aux+'/'+chan1.code+'/'+chan2.code, parameters=xcorr_header)
                    except IOError:
                        skipflag=True
                        break
        if deletesac:
            shutil.rmtree(outdir+'/'+pfx)
        print 'End read data into ASDF database'
        return
                    
    def xcorr_rotation(self, outdir=None, pfx='COR'):
        """Rotate cross-correlation data 
        ===========================================================================================================
        Input Parameters:
        outdir                  - output directory for sac files (None is not to write)
        pfx                     - prefix
        -----------------------------------------------------------------------------------------------------------
        Output:
        ASDF path           : self.auxiliary_data.NoiseXcorr[netcode1][stacode1][netcode2][stacode2][chan1][chan2]
        sac file(optional)  : outdir/COR/TA.G12A/COR_TA.G12A_BHT_TA.R21A_BHT.SAC
        ===========================================================================================================
        """
        staLst=self.waveforms.list()
        for staid1 in staLst:
            for staid2 in staLst:
                netcode1, stacode1=staid1.split('.')
                netcode2, stacode2=staid2.split('.')
                if stacode1 >= stacode2:
                    continue
                chan1E=None; chan1N=None; chan1Z=None; chan2E=None; chan2N=None; chan2Z=None
                try:
                    channels1=self.auxiliary_data.NoiseXcorr[netcode1][stacode1][netcode2][stacode2].list()
                    channels2=self.auxiliary_data.NoiseXcorr[netcode1][stacode1][netcode2][stacode2][channels1[0]].list()
                    cpfx1=channels1[0][:2]
                    cpfx2=channels2[0][:2]
                    for chan in channels1:
                        if chan[2]=='E': chan1E=chan
                        if chan[2]=='N': chan1N=chan
                        if chan[2]=='Z': chan1Z=chan
                    for chan in channels2:
                        if chan[2]=='E': chan2E=chan
                        if chan[2]=='N': chan2N=chan
                        if chan[2]=='Z': chan2Z=chan
                except AttributeError:
                    continue
                subdset=self.auxiliary_data.NoiseXcorr[netcode1][stacode1][netcode2][stacode2]
                if chan1E==None or chan1N==None or chan2E==None or chan2N==None:
                    continue
                if chan1Z==None or chan2Z==None:
                    print 'Do rotation(RT) for:'+netcode1+'.'+stacode1+' and '+netcode2+'.'+stacode2
                else:
                    print 'Do rotation(RTZ) for:'+netcode1+'.'+stacode1+' and '+netcode2+'.'+stacode2
                dsetEE=subdset[chan1E][chan2E]
                dsetEN=subdset[chan1E][chan2N]
                dsetNE=subdset[chan1N][chan2E]
                dsetNN=subdset[chan1N][chan2N]
                temp_header=dsetEE.parameters.copy()
                chan1R=cpfx1+'R'; chan1T=cpfx1+'T'; chan2R=cpfx2+'R'; chan2T=cpfx2+'T'
                theta=temp_header['az']
                psi=temp_header['baz']
                Ctheta=np.cos(np.pi*theta/180.)
                Stheta=np.sin(np.pi*theta/180.)
                Cpsi=np.cos(np.pi*psi/180.)
                Spsi=np.sin(np.pi*psi/180.)
                tempTT=-Ctheta*Cpsi*dsetEE.data.value+Ctheta*Spsi*dsetEN.data.value - \
                    Stheta*Spsi*dsetNN.data.value + Stheta*Cpsi*dsetNE.data.value
                
                tempRR=- Stheta*Spsi*dsetEE.data.value - Stheta*Cpsi*dsetEN.data.value \
                    - Ctheta*Cpsi*dsetNN.data.value - Ctheta*Spsi*dsetNE.data.value
                
                tempTR=-Ctheta*Spsi*dsetEE.data.value - Ctheta*Cpsi*dsetEN.data.value  \
                    + Stheta*Cpsi*dsetNN.data.value + Stheta*Spsi*dsetNE.data.value
                
                tempRT=-Stheta*Cpsi*dsetEE.data.value +Stheta*Spsi*dsetEN.data.value \
                    + Ctheta*Spsi*dsetNN.data.value - Ctheta*Cpsi*dsetNE.data.value
                staid_aux=netcode1+'/'+stacode1+'/'+netcode2+'/'+stacode2
                temp_header['chan1']=chan1T; temp_header['chan2']=chan2T
                self.add_auxiliary_data(data=tempTT, data_type='NoiseXcorr', path=staid_aux+'/'+chan1T+'/'+chan2T, parameters=temp_header)
                
                temp_header['chan1']=chan1R; temp_header['chan2']=chan2R
                self.add_auxiliary_data(data=tempRR, data_type='NoiseXcorr', path=staid_aux+'/'+chan1R+'/'+chan2R, parameters=temp_header)
                
                temp_header['chan1']=chan1T; temp_header['chan2']=chan2R
                self.add_auxiliary_data(data=tempTR, data_type='NoiseXcorr', path=staid_aux+'/'+chan1T+'/'+chan2R, parameters=temp_header)
                
                temp_header['chan1']=chan1R; temp_header['chan2']=chan2T
                self.add_auxiliary_data(data=tempRT, data_type='NoiseXcorr', path=staid_aux+'/'+chan1R+'/'+chan2T, parameters=temp_header)
                # write to sac files
                if outdir!=None:
                    self.wsac_xcorr(netcode1=netcode1, stacode1=stacode1, netcode2=netcode2,
                            stacode2=stacode2, chan1=chan1T, chan2=chan2T, outdir=outdir, pfx=pfx)
                    self.wsac_xcorr(netcode1=netcode1, stacode1=stacode1, netcode2=netcode2,
                            stacode2=stacode2, chan1=chan1R, chan2=chan2R, outdir=outdir, pfx=pfx)
                    self.wsac_xcorr(netcode1=netcode1, stacode1=stacode1, netcode2=netcode2,
                            stacode2=stacode2, chan1=chan1T, chan2=chan2R, outdir=outdir, pfx=pfx)
                    self.wsac_xcorr(netcode1=netcode1, stacode1=stacode1, netcode2=netcode2,
                            stacode2=stacode2, chan1=chan1R, chan2=chan2T, outdir=outdir, pfx=pfx)
                # RTZ rotation
                if chan1Z!=None and chan2Z!=None:
                    dsetEZ=subdset[chan1E][chan2Z]
                    dsetZE=subdset[chan1Z][chan2E]
                    dsetNZ=subdset[chan1N][chan2Z]
                    dsetZN=subdset[chan1Z][chan2N]
                    tempRZ = Ctheta*dsetNZ.data.value + Stheta*dsetEZ.data.value
                    tempZR = - Cpsi*dsetZN.data.value -Spsi*dsetZE.data.value
                    tempTZ = -Stheta*dsetNZ.data.value + Ctheta*dsetEZ.data.value
                    tempZT =  Spsi*dsetZN.data.value - Cpsi*dsetZE.data.value
                    temp_header['chan1']=chan1R; temp_header['chan2']=chan2Z
                    self.add_auxiliary_data(data=tempRZ, data_type='NoiseXcorr', path=staid_aux+'/'+chan1R+'/'+chan2Z, parameters=temp_header)
                    temp_header['chan1']=chan1Z; temp_header['chan2']=chan2R
                    self.add_auxiliary_data(data=tempZR, data_type='NoiseXcorr', path=staid_aux+'/'+chan1Z+'/'+chan2R, parameters=temp_header)
                    temp_header['chan1']=chan1T; temp_header['chan2']=chan2Z
                    self.add_auxiliary_data(data=tempTZ, data_type='NoiseXcorr', path=staid_aux+'/'+chan1T+'/'+chan2Z, parameters=temp_header)
                    temp_header['chan1']=chan1Z; temp_header['chan2']=chan2T
                    self.add_auxiliary_data(data=tempZT, data_type='NoiseXcorr', path=staid_aux+'/'+chan1Z+'/'+chan2T, parameters=temp_header)
                    # write to sac files
                    if outdir!=None:
                        self.wsac_xcorr(netcode1=netcode1, stacode1=stacode1, netcode2=netcode2,
                                stacode2=stacode2, chan1=chan1R, chan2=chan2Z, outdir=outdir, pfx=pfx)                        
                        self.wsac_xcorr(netcode1=netcode1, stacode1=stacode1, netcode2=netcode2,
                                stacode2=stacode2, chan1=chan1Z, chan2=chan2R, outdir=outdir, pfx=pfx)
                        self.wsac_xcorr(netcode1=netcode1, stacode1=stacode1, netcode2=netcode2,
                                stacode2=stacode2, chan1=chan1T, chan2=chan2Z, outdir=outdir, pfx=pfx)
                        self.wsac_xcorr(netcode1=netcode1, stacode1=stacode1, netcode2=netcode2,
                                stacode2=stacode2, chan1=chan1Z, chan2=chan2T, outdir=outdir, pfx=pfx)
        return
    
    def xcorr_prephp(self, outdir, mapfile='./MAPS/smpkolya_phv'):
        """
        Generate predicted phase velocity dispersion curves for cross-correlation pairs
        ====================================================================================
        Input Parameters:
        outdir  - output directory
        mapfile - phase velocity maps
        ------------------------------------------------------------------------------------
        Input format:
        prephaseEXE pathfname mapfile perlst staname
        
        Output format:
        outdirL(outdirR)/evid.staid.pre
        ====================================================================================
        """
        staLst=self.waveforms.list()
        for evid in staLst:
            evnetcode, evstacode=evid.split('.')
            evla, evz, evlo=self.waveforms[evid].coordinates.values()
            pathfname=evid+'_pathfile'
            prephaseEXE='./mhr_grvel_predict/lf_mhr_predict_earth'
            perlst='./mhr_grvel_predict/perlist_phase'
            if not os.path.isfile(prephaseEXE):
                print 'lf_mhr_predict_earth executable does not exist!'
                return
            if not os.path.isfile(perlst):
                print 'period list does not exist!'
                return
            with open(pathfname,'w') as f:
                ista=0
                for station_id in staLst:
                    stacode=station_id.split('.')[1]
                    if evid >= station_id:
                        continue
                    stla, stz, stlo=self.waveforms[station_id].coordinates.values()
                    if ( abs(stlo-evlo) < 0.1 and abs(stla-evla)<0.1 ):
                        continue
                    ista=ista+1
                    f.writelines('%5d%5d %15s %15s %10.5f %10.5f %10.5f %10.5f \n'
                            %(1, ista, evid, station_id, evla, evlo, stla, stlo ))
            call([prephaseEXE, pathfname, mapfile, perlst, evid])
            os.remove(pathfname)
            outdirL=outdir+'_L'
            outdirR=outdir+'_R'
            if not os.path.isdir(outdirL):
                os.makedirs(outdirL)
            if not os.path.isdir(outdirR):
                os.makedirs(outdirR)
            fout = open(evid+'_temp','wb')
            for l1 in open('PREDICTION_L'+'_'+evid):
                l2 = l1.rstrip().split()
                if (len(l2)>8):
                    fout.close()
                    outname = outdirL + "/%s.%s.pre" % (l2[3],l2[4])
                    fout = open(outname,"w")
                elif (len(l2)>7):
                    fout.close()
                    outname = outdirL + "/%s.%s.pre" % (l2[2],l2[3])
                    fout = open(outname,"w")                
                else:
                    fout.write("%g %g\n" % (float(l2[0]),float(l2[1])))
            for l1 in open('PREDICTION_R'+'_'+evid):
                l2 = l1.rstrip().split()
                if (len(l2)>8):
                    fout.close()
                    outname = outdirR + "/%s.%s.pre" % (l2[3],l2[4])
                    fout = open(outname,"w")
                elif (len(l2)>7):
                    fout.close()
                    outname = outdirR + "/%s.%s.pre" % (l2[2],l2[3])
                    fout = open(outname,"w")         
                else:
                    fout.write("%g %g\n" % (float(l2[0]),float(l2[1])))
            fout.close()
            os.remove(evid+'_temp')
            os.remove('PREDICTION_L'+'_'+evid)
            os.remove('PREDICTION_R'+'_'+evid)
        return
    
    def xcorr_aftan(self, channel='ZZ', tb=0., outdir=None, inftan=pyaftan.InputFtanParam(), basic1=True, basic2=True, \
            pmf1=True, pmf2=True, verbose=True, prephdir=None, f77=True, pfx='DISP'):
        """ aftan analysis of cross-correlation data 
        =======================================================================================
        Input Parameters:
        channel     - channel pair for aftan analysis(e.g. 'ZZ', 'TT', 'ZR', 'RZ'...)
        tb          - begin time (default = 0.0)
        outdir      - directory for output disp txt files (default = None, no txt output)
        inftan      - input aftan parameters
        basic1      - save basic aftan results or not
        basic2      - save basic aftan results(with jump correction) or not
        pmf1        - save pmf aftan results or not
        pmf2        - save pmf aftan results(with jump correction) or not
        prephdir    - directory for predicted phase velocity dispersion curve
        f77         - use aftanf77 or not
        pfx         - prefix for output txt DISP files
        ---------------------------------------------------------------------------------------
        Output:
        self.auxiliary_data.DISPbasic1, self.auxiliary_data.DISPbasic2,
        self.auxiliary_data.DISPpmf1, self.auxiliary_data.DISPpmf2
        =======================================================================================
        """
        print 'Start aftan analysis!'
        staLst=self.waveforms.list()
        for staid1 in staLst:
            for staid2 in staLst:
                netcode1, stacode1=staid1.split('.')
                netcode2, stacode2=staid2.split('.')
                if staid1 >= staid2: continue
                try:
                    channels1=self.auxiliary_data.NoiseXcorr[netcode1][stacode1][netcode2][stacode2].list()
                    channels2=self.auxiliary_data.NoiseXcorr[netcode1][stacode1][netcode2][stacode2][channels1[0]].list()
                    for chan in channels1:
                        if chan[2]==channel[0]: chan1=chan
                    for chan in channels2:
                        if chan[2]==channel[1]: chan2=chan
                except KeyError:
                    continue
                try:
                    tr=self.get_xcorr_trace(netcode1, stacode1, netcode2, stacode2, chan1, chan2)
                except NameError:
                    print netcode1+'.'+stacode1+'_'+netcode2+'.'+stacode2+'_'+channel+' not exists!'
                    continue
                aftanTr=pyaftan.aftantrace(tr.data, tr.stats)
                if abs(aftanTr.stats.sac.b+aftanTr.stats.sac.e)<aftanTr.stats.delta:
                    aftanTr.makesym()
                if prephdir !=None:
                    phvelname = prephdir + "/%s.%s.pre" %(netcode1+'.'+stacode1, netcode2+'.'+stacode2)
                else:
                    phvelname =''
                if f77:
                    aftanTr.aftanf77(pmf=inftan.pmf, piover4=inftan.piover4, vmin=inftan.vmin, vmax=inftan.vmax, tmin=inftan.tmin, tmax=inftan.tmax,
                        tresh=inftan.tresh, ffact=inftan.ffact, taperl=inftan.taperl, snr=inftan.snr, fmatch=inftan.fmatch, nfin=inftan.nfin,
                            npoints=inftan.npoints, perc=inftan.perc, phvelname=phvelname)
                else:
                    aftanTr.aftan(pmf=inftan.pmf, piover4=inftan.piover4, vmin=inftan.vmin, vmax=inftan.vmax, tmin=inftan.tmin, tmax=inftan.tmax,
                        tresh=inftan.tresh, ffact=inftan.ffact, taperl=inftan.taperl, snr=inftan.snr, fmatch=inftan.fmatch, nfin=inftan.nfin,
                            npoints=inftan.npoints, perc=inftan.perc, phvelname=phvelname)
                if verbose:
                    print 'aftan analysis for: ' + netcode1+'.'+stacode1+'_'+netcode2+'.'+stacode2+'_'+channel
                aftanTr.get_snr(ffact=inftan.ffact) # SNR analysis
                staid_aux=netcode1+'/'+stacode1+'/'+netcode2+'/'+stacode2+'/'+channel
                # save aftan results to ASDF dataset
                if basic1:
                    parameters={'Tc': 0, 'To': 1, 'Vgr': 2, 'Vph': 3, 'ampdb': 4, 'dis': 5, 'snrdb': 6, 'mhw': 7, 'amp': 8, 'Np': aftanTr.ftanparam.nfout1_1}
                    self.add_auxiliary_data(data=aftanTr.ftanparam.arr1_1, data_type='DISPbasic1', path=staid_aux, parameters=parameters)
                if basic2:
                    parameters={'Tc': 0, 'To': 1, 'Vgr': 2, 'Vph': 3, 'ampdb': 4, 'snrdb': 5, 'mhw': 6, 'amp': 7, 'Np': aftanTr.ftanparam.nfout2_1}
                    self.add_auxiliary_data(data=aftanTr.ftanparam.arr2_1, data_type='DISPbasic2', path=staid_aux, parameters=parameters)
                if inftan.pmf:
                    if pmf1:
                        parameters={'Tc': 0, 'To': 1, 'Vgr': 2, 'Vph': 3, 'ampdb': 4, 'dis': 5, 'snrdb': 6, 'mhw': 7, 'amp': 8, 'Np': aftanTr.ftanparam.nfout1_2}
                        self.add_auxiliary_data(data=aftanTr.ftanparam.arr1_2, data_type='DISPpmf1', path=staid_aux, parameters=parameters)
                    if pmf2:
                        parameters={'Tc': 0, 'To': 1, 'Vgr': 2, 'Vph': 3, 'ampdb': 4, 'snrdb': 5, 'mhw': 6, 'amp': 7, 'snr':8, 'Np': aftanTr.ftanparam.nfout2_2}
                        self.add_auxiliary_data(data=aftanTr.ftanparam.arr2_2, data_type='DISPpmf2', path=staid_aux, parameters=parameters)
                if outdir != None:
                    if not os.path.isdir(outdir+'/'+pfx+'/'+staid1):
                        os.makedirs(outdir+'/'+pfx+'/'+staid1)
                    foutPR=outdir+'/'+pfx+'/'+netcode1+'.'+stacode1+'/'+ \
                                    pfx+'_'+netcode1+'.'+stacode1+'_'+chan1+'_'+netcode2+'.'+stacode2+'_'+chan2+'.SAC'
                    aftanTr.ftanparam.writeDISP(foutPR)
        print 'End aftan analysis!'
        return
               
    def xcorr_aftan_mp(self, outdir, channel='ZZ', tb=0., inftan=pyaftan.InputFtanParam(), basic1=True, basic2=True,
            pmf1=True, pmf2=True, verbose=True, prephdir=None, f77=True, pfx='DISP', subsize=1000, deletedisp=True, nprocess=None):
        """ aftan analysis of cross-correlation data with multiprocessing
        =======================================================================================
        Input Parameters:
        channel     - channel pair for aftan analysis(e.g. 'ZZ', 'TT', 'ZR', 'RZ'...)
        tb          - begin time (default = 0.0)
        outdir      - directory for output disp binary files
        inftan      - input aftan parameters
        basic1      - save basic aftan results or not
        basic2      - save basic aftan results(with jump correction) or not
        pmf1        - save pmf aftan results or not
        pmf2        - save pmf aftan results(with jump correction) or not
        prephdir    - directory for predicted phase velocity dispersion curve
        f77         - use aftanf77 or not
        pfx         - prefix for output txt DISP files
        subsize     - subsize of processing list, use to prevent lock in multiprocessing process
        deletedisp  - delete output dispersion files or not
        nprocess    - number of processes
        ---------------------------------------------------------------------------------------
        Output:
        self.auxiliary_data.DISPbasic1, self.auxiliary_data.DISPbasic2,
        self.auxiliary_data.DISPpmf1, self.auxiliary_data.DISPpmf2
        =======================================================================================
        """
        print 'Preparing data for aftan analysis !'
        staLst=self.waveforms.list()
        inputStream=[]
        for staid1 in staLst:
            if not os.path.isdir(outdir+'/'+pfx+'/'+staid1):
                os.makedirs(outdir+'/'+pfx+'/'+staid1)
            for staid2 in staLst:
                netcode1, stacode1=staid1.split('.')
                netcode2, stacode2=staid2.split('.')
                if staid1 >= staid2: continue
                try:
                    channels1=self.auxiliary_data.NoiseXcorr[netcode1][stacode1][netcode2][stacode2].list()
                    channels2=self.auxiliary_data.NoiseXcorr[netcode1][stacode1][netcode2][stacode2][channels1[0]].list()
                    for chan in channels1:
                        if chan[2]==channel[0]: chan1=chan
                    for chan in channels2:
                        if chan[2]==channel[1]: chan2=chan
                except KeyError:
                    continue
                try:
                    tr=self.get_xcorr_trace(netcode1, stacode1, netcode2, stacode2, chan1, chan2)
                except NameError:
                    print netcode1+'.'+stacode1+'_'+netcode2+'.'+stacode2+'_'+channel+' not exists!'
                    continue
                if verbose:
                    print 'Preparing aftan data: '+ netcode1+'.'+stacode1+'_'+netcode2+'.'+stacode2+'_'+channel
                aftanTr=pyaftan.aftantrace(tr.data, tr.stats)
                inputStream.append(aftanTr)
        print 'Start multiprocessing aftan analysis !'
        if len(inputStream) > subsize:
            Nsub = int(len(inputStream)/subsize)
            for isub in xrange(Nsub):
                print isub,'in',Nsub
                cstream=inputStream[isub*subsize:(isub+1)*subsize]
                AFTAN = partial(aftan4mp, outdir=outdir, inftan=inftan, prephdir=prephdir, f77=f77, pfx=pfx)
                pool = multiprocessing.Pool(processes=nprocess)
                pool.map(AFTAN, cstream) #make our results with a map call
                pool.close() #we are not adding any more processes
                pool.join() #tell it to wait until all threads are done before going on
            cstream=inputStream[(isub+1)*subsize:]
            AFTAN = partial(aftan4mp, outdir=outdir, inftan=inftan, prephdir=prephdir, f77=f77, pfx=pfx)
            pool = multiprocessing.Pool(processes=nprocess)
            pool.map(AFTAN, cstream) #make our results with a map call
            pool.close() #we are not adding any more processes
            pool.join() #tell it to wait until all threads are done before going on
        else:
            AFTAN = partial(aftan4mp, outdir=outdir, inftan=inftan, prephdir=prephdir, f77=f77, pfx=pfx)
            pool = multiprocessing.Pool(processes=nprocess)
            pool.map(AFTAN, inputStream) #make our results with a map call
            pool.close() #we are not adding any more processes
            pool.join() #tell it to wait until all threads are done before going on
        print 'End of multiprocessing aftan analysis !'
        print 'Reading aftan results into ASDF Dataset !'
        for staid1 in staLst:
            for staid2 in staLst:
                netcode1, stacode1=staid1.split('.')
                netcode2, stacode2=staid2.split('.')
                if stacode1 >= stacode2: continue
                try:
                    channels1=self.auxiliary_data.NoiseXcorr[netcode1][stacode1][netcode2][stacode2].list()
                    channels2=self.auxiliary_data.NoiseXcorr[netcode1][stacode1][netcode2][stacode2][channels1[0]].list()
                    for chan in channels1:
                        if chan[2]==channel[0]: chan1=chan
                    for chan in channels2:
                        if chan[2]==channel[1]: chan2=chan
                except KeyError: continue
                finPR=pfx+'/'+netcode1+'.'+stacode1+'/'+ \
                        pfx+'_'+netcode1+'.'+stacode1+'_'+chan1+'_'+netcode2+'.'+stacode2+'_'+chan2+'.SAC'
                try:
                    f10=np.load(outdir+'/'+finPR+'_1_DISP.0.npz')
                    f11=np.load(outdir+'/'+finPR+'_1_DISP.1.npz')
                    f20=np.load(outdir+'/'+finPR+'_2_DISP.0.npz')
                    f21=np.load(outdir+'/'+finPR+'_2_DISP.1.npz')
                except IOError:
                    print 'NO aftan results: '+ netcode1+'.'+stacode1+'_'+netcode2+'.'+stacode2+'_'+channel
                    continue
                print 'Reading aftan results '+ netcode1+'.'+stacode1+'_'+netcode2+'.'+stacode2+'_'+channel
                if deletedisp:
                    os.remove(outdir+'/'+finPR+'_1_DISP.0.npz')
                    os.remove(outdir+'/'+finPR+'_1_DISP.1.npz')
                    os.remove(outdir+'/'+finPR+'_2_DISP.0.npz')
                    os.remove(outdir+'/'+finPR+'_2_DISP.1.npz')
                arr1_1=f10['arr_0']
                nfout1_1=f10['arr_1']
                arr2_1=f11['arr_0']
                nfout2_1=f11['arr_1']
                arr1_2=f20['arr_0']
                nfout1_2=f20['arr_1']
                arr2_2=f21['arr_0']
                nfout2_2=f21['arr_1']
                staid_aux=netcode1+'/'+stacode1+'/'+netcode2+'/'+stacode2+'/'+channel
                if basic1:
                    parameters={'Tc': 0, 'To': 1, 'Vgr': 2, 'Vph': 3, 'ampdb': 4, 'dis': 5, 'snrdb': 6, 'mhw': 7, 'amp': 8, 'Np': nfout1_1}
                    self.add_auxiliary_data(data=arr1_1, data_type='DISPbasic1', path=staid_aux, parameters=parameters)
                if basic2:
                    parameters={'Tc': 0, 'To': 1, 'Vgr': 2, 'Vph': 3, 'ampdb': 4, 'snrdb': 5, 'mhw': 6, 'amp': 7, 'Np': nfout2_1}
                    self.add_auxiliary_data(data=arr2_1, data_type='DISPbasic2', path=staid_aux, parameters=parameters)
                if inftan.pmf:
                    if pmf1:
                        parameters={'Tc': 0, 'To': 1, 'Vgr': 2, 'Vph': 3, 'ampdb': 4, 'dis': 5, 'snrdb': 6, 'mhw': 7, 'amp': 8, 'Np': nfout1_2}
                        self.add_auxiliary_data(data=arr1_2, data_type='DISPpmf1', path=staid_aux, parameters=parameters)
                    if pmf2:
                        parameters={'Tc': 0, 'To': 1, 'Vgr': 2, 'Vph': 3, 'ampdb': 4, 'snrdb': 5, 'mhw': 6, 'amp': 7, 'snr':8, 'Np': nfout2_2}
                        self.add_auxiliary_data(data=arr2_2, data_type='DISPpmf2', path=staid_aux, parameters=parameters)
        if deletedisp:
            shutil.rmtree(outdir+'/'+pfx)
        return
    
    def interp_disp(self, data_type='DISPpmf2', channel='ZZ', pers=np.array([]), verbose=True):
        """ Interpolate dispersion curve for a given period array.
        =======================================================================================================
        Input Parameters:
        data_type   - dispersion data type (default = DISPpmf2, pmf aftan results after jump detection)
        pers        - period array
        
        Output:
        self.auxiliary_data.DISPbasic1interp, self.auxiliary_data.DISPbasic2interp,
        self.auxiliary_data.DISPpmf1interp, self.auxiliary_data.DISPpmf2interp
        =======================================================================================================
        """
        if data_type=='DISPpmf2':
            ntype=6
        else:
            ntype=5
        if pers.size==0:
            pers=np.append( np.arange(18.)*2.+6., np.arange(4.)*5.+45.)
        staLst=self.waveforms.list()
        for staid1 in staLst:
            for staid2 in staLst:
                netcode1, stacode1=staid1.split('.')
                netcode2, stacode2=staid2.split('.')
                if staid1 >= staid2: continue
                try:
                    subdset=self.auxiliary_data[data_type][netcode1][stacode1][netcode2][stacode2][channel]
                except:
                    continue
                data=subdset.data.value
                index=subdset.parameters
                if verbose:
                    print 'Interpolating dispersion curve for '+ netcode1+'.'+stacode1+'_'+netcode2+'.'+stacode2+'_'+channel
                outindex={ 'To': 0, 'Vgr': 1, 'Vph': 2,  'amp': 3, 'snr': 4, 'inbound': 5, 'Np': pers.size }
                Np=int(index['Np'])
                if Np < 5:
                    warnings.warn('Not enough datapoints for: '+ netcode1+'.'+stacode1+'_'+netcode2+'.'+stacode2+'_'+channel, UserWarning, stacklevel=1)
                    continue
                obsT=data[index['To']][:Np]
                Vgr=np.interp(pers, obsT, data[index['Vgr']][:Np] )
                Vph=np.interp(pers, obsT, data[index['Vph']][:Np] )
                amp=np.interp(pers, obsT, data[index['amp']][:Np] )
                inbound=(pers > obsT[0])*(pers < obsT[-1])*1
                interpdata=np.append(pers, Vgr)
                interpdata=np.append(interpdata, Vph)
                interpdata=np.append(interpdata, amp)
                if data_type=='DISPpmf2':
                    snr=np.interp(pers, obsT, data[index['snr']][:Np] )
                    interpdata=np.append(interpdata, snr)
                interpdata=np.append(interpdata, inbound)
                interpdata=interpdata.reshape(ntype, pers.size)
                staid_aux=netcode1+'/'+stacode1+'/'+netcode2+'/'+stacode2+'/'+channel
                self.add_auxiliary_data(data=interpdata, data_type=data_type+'interp', path=staid_aux, parameters=outindex)
        return
    
    def xcorr_raytomoinput_deprecated(self, outdir, channel='ZZ', pers=np.array([]), outpfx='raytomo_in_', data_type='DISPpmf2interp', verbose=True):
        """
        Generate Input files for Barmine's straight ray surface wave tomography code.
        =======================================================================================================
        Input Parameters:
        outdir      - output directory
        channel     - channel for tomography
        pers        - period array
        outpfx      - prefix for output files, default is 'MISHA_in_'
        data_type   - dispersion data type (default = DISPpmf2, pmf aftan results after jump detection)
        -------------------------------------------------------------------------------------------------------
        Output format:
        outdir/outpfx+per_channel_ph.lst
        =======================================================================================================
        """
        if not os.path.isdir(outdir):
            os.makedirs(outdir)
        if pers.size==0:
            pers=np.append( np.arange(18.)*2.+6., np.arange(4.)*5.+45.)
        staLst=self.waveforms.list()
        for per in pers:
            print 'Generating Tomo Input for period:', per
            fname_ph=outdir+'/'+outpfx+'%g'%( per ) +'_'+channel+'_ph.lst' %( per )
            fname_gr=outdir+'/'+outpfx+'%g'%( per ) +'_'+channel+'_gr.lst' %( per )
            fph=open(fname_ph, 'w')
            fgr=open(fname_gr, 'w')
            i=-1
            for staid1 in staLst:
                for staid2 in staLst:
                    netcode1, stacode1=staid1.split('.')
                    netcode2, stacode2=staid2.split('.')
                    if staid1 >= staid2: continue
                    i=i+1
                    try:
                        subdset=self.auxiliary_data[data_type][netcode1][stacode1][netcode2][stacode2][channel]
                    except:
                        # warnings.warn('No interpolated dispersion curve: ' + netcode1+'.'+stacode1+'_'+netcode2+'.'+stacode2+'_'+channel,
                        #             UserWarning, stacklevel=1)
                        continue
                    lat1, elv1, lon1=self.waveforms[staid1].coordinates.values()
                    lat2, elv2, lon2=self.waveforms[staid2].coordinates.values()
                    dist, az, baz=obspy.geodetics.gps2dist_azimuth(lat1, lon1, lat2, lon2) # distance is in m
                    dist=dist/1000.
                    if dist < 2.*per*3.5: continue
                    if lon1<0: lon1+=360.
                    if lon2<0: lon2+=360.
                    data=subdset.data.value
                    index=subdset.parameters
                    ind_per=np.where(data[index['To']][:] == per)[0]
                    if ind_per.size==0:
                        raise AttributeError('No interpolated dispersion curve data for period='+str(per)+' sec!')
                    pvel=data[index['Vph']][ind_per]
                    gvel=data[index['Vgr']][ind_per]
                    snr=data[index['snr']][ind_per]
                    amp=data[index['amp']][ind_per]
                    inbound=data[index['inbound']][ind_per]
                    # quality control
                    if pvel < 0 or gvel < 0 or pvel>10 or gvel>10 or snr >1e10 or amp >1e10: continue
                    if inbound!=1.: continue
                    if snr < 15.: continue
                    fph.writelines("%d %g %g %g %g %g 1. %s %s 1 1 \n" %(i, lat1, lon1, lat2, lon2, pvel, staid1, staid2))
                    fgr.writelines("%d %g %g %g %g %g 1. %s %s 1 1 \n" %(i, lat1, lon1, lat2, lon2, gvel, staid1, staid2))
                    # fph.writelines("%g %g %g %g %g 1. %s %s 1 1 \n" %(lat1, lon1, lat2, lon2, pvel, staid1, staid2))
                    # fgr.writelines("%g %g %g %g %g 1. %s %s 1 1 \n" %(lat1, lon1, lat2, lon2, gvel, staid1, staid2))
            fph.close()
            fgr.close()
        print 'End of Generating Misha Tomography Input File!'
        return
    
    
    def xcorr_raytomoinput(self, outdir, channel='ZZ', pers=np.array([]), outpfx='raytomo_in_', data_type='DISPpmf2interp', verbose=True):
        """
        Generate Input files for Barmine's straight ray surface wave tomography code.
        =======================================================================================================
        Input Parameters:
        outdir      - output directory
        channel     - channel for tomography
        pers        - period array
        outpfx      - prefix for output files, default is 'MISHA_in_'
        data_type   - dispersion data type (default = DISPpmf2, pmf aftan results after jump detection)
        -------------------------------------------------------------------------------------------------------
        Output format:
        outdir/outpfx+per_channel_ph.lst
        =======================================================================================================
        """
        if not os.path.isdir(outdir):
            os.makedirs(outdir)
        if pers.size==0:
            pers=np.append( np.arange(18.)*2.+6., np.arange(4.)*5.+45.)
        fph_lst=[]
        fgr_lst=[]
        for per in pers:
            fname_ph=outdir+'/'+outpfx+'%g'%( per ) +'_'+channel+'_ph.lst' %( per )
            fname_gr=outdir+'/'+outpfx+'%g'%( per ) +'_'+channel+'_gr.lst' %( per )
            fph=open(fname_ph, 'w')
            fgr=open(fname_gr, 'w')
            fph_lst.append(fph)
            fgr_lst.append(fgr)
        staLst=self.waveforms.list()
        i=-1
        for staid1 in staLst:
            for staid2 in staLst:
                netcode1, stacode1=staid1.split('.')
                netcode2, stacode2=staid2.split('.')
                if staid1 >= staid2: continue
                i=i+1
                try:
                    subdset=self.auxiliary_data[data_type][netcode1][stacode1][netcode2][stacode2][channel]
                except:
                    continue
                lat1, elv1, lon1=self.waveforms[staid1].coordinates.values()
                lat2, elv2, lon2=self.waveforms[staid2].coordinates.values()
                dist, az, baz=obspy.geodetics.gps2dist_azimuth(lat1, lon1, lat2, lon2) # distance is in m
                dist=dist/1000.
                if lon1<0: lon1+=360.
                if lon2<0: lon2+=360.
                data=subdset.data.value
                index=subdset.parameters
                for iper in xrange(pers.size):
                    per=pers[iper]
                    if dist < 2.*per*3.5: continue
                    ind_per=np.where(data[index['To']][:] == per)[0]
                    if ind_per.size==0:
                        raise AttributeError('No interpolated dispersion curve data for period='+str(per)+' sec!')
                    pvel=data[index['Vph']][ind_per]
                    gvel=data[index['Vgr']][ind_per]
                    snr=data[index['snr']][ind_per]
                    amp=data[index['amp']][ind_per]
                    inbound=data[index['inbound']][ind_per]
                    # quality control
                    if pvel < 0 or gvel < 0 or pvel>10 or gvel>10 or snr >1e10 or amp >1e10: continue
                    if inbound!=1.: continue
                    if snr < 15.: continue
                    fph=fph_lst[iper]
                    fgr=fgr_lst[iper]
                    fph.writelines("%d %g %g %g %g %g 1. %s %s 1 1 \n" %(i, lat1, lon1, lat2, lon2, pvel, staid1, staid2))
                    fgr.writelines("%d %g %g %g %g %g 1. %s %s 1 1 \n" %(i, lat1, lon1, lat2, lon2, gvel, staid1, staid2))
                    # fph.writelines("%g %g %g %g %g 1. %s %s 1 1 \n" %(lat1, lon1, lat2, lon2, pvel, staid1, staid2))
                    # fgr.writelines("%g %g %g %g %g 1. %s %s 1 1 \n" %(lat1, lon1, lat2, lon2, gvel, staid1, staid2))
        for iper in xrange(pers.size):
            fph=fph_lst[iper]
            fgr=fgr_lst[iper]
            fph.close()
            fgr.close()
        print 'End of Generating Misha Tomography Input File!'
        return
    
    
    
    # 
    # def get_field(self, data_type='DISPpmf2', fieldtype='Vgr', pers=np.array([10.]), outdir=None, distflag=True, verbose=True ):
    #     """ Get the field data
    #     =======================================================================================
    #     Input Parameters:
    #     data_type   - dispersion data type (default = DISPpmf2, pmf aftan results after jump detection)
    #     fieldtype   - field data type( Vgr, Vph, Amp)
    #     pers        - period array
    #     outdir      - directory for txt output
    #     distflag    - whether to output distance or not
    #     Output:
    #     self.auxiliary_data.FieldDISPbasic1interp, self.auxiliary_data.FieldDISPbasic2interp,
    #     self.auxiliary_data.FieldDISPpmf1interp, self.auxiliary_data.FieldDISPpmf2interp
    #     =======================================================================================
    #     """
    #     data_type=data_type+'interp'
    #     tempdict={'Vgr': 'Tgr', 'Vph': 'Tph', 'amp': 'Amp', 'ms':'Ms'}
    #     if distflag:
    #         outindex={ 'longitude': 0, 'latitude': 1, tempdict[fieldtype]: 2,  'dist': 3 }
    #     else:
    #         outindex={ 'longitude': 0, 'latitude': 1, tempdict[fieldtype]: 2 }
    #     staidLst=self.auxiliary_data[data_type].list()
    #     evlo=self.events.events[0].origins[0].longitude
    #     evla=self.events.events[0].origins[0].latitude
    #     for per in pers:
    #         FieldArr=np.array([])
    #         Nfp=0
    #         for staid in staidLst:
    #             subdset = self.auxiliary_data[data_type][staid]
    #             data=subdset.data.value
    #             index=subdset.parameters
    #             knetwk=str(subdset.parameters['knetwk'])
    #             kstnm=str(subdset.parameters['kstnm'])
    #             station_id=knetwk+'.'+kstnm
    #             obsT=data[index['To']]
    #             if verbose:
    #                 print 'Getting field data from '+ station_id
    #             if fieldtype=='ms':
    #                 outdata=data[index['Vgr']]
    #             else:
    #                 outdata=data[index[fieldtype]]
    #             inbound=data[index['inbound']]
    #             fieldpoint=outdata[obsT==per]
    #             if fieldpoint == np.nan or fieldpoint<=0:
    #                 print station_id+' has invalid value'+' T='+str(per)+'s'
    #                 continue
    #             # print fieldpoint
    #             inflag=inbound[obsT==per]
    #             if fieldpoint.size==0:
    #                 print 'No datapoint for'+ station_id+' T='+per+'s in interpolated disp dataset!'
    #                 continue
    #             if inflag == 0:
    #                 print 'Datapoint out of bound: '+ knetwk+'.'+kstnm+' T='+str(per)+'s!'
    #                 continue
    #             if fieldtype=='ms':
    #                 subdset=self.waveforms[station_id]
    #                 tr=subdset.ses3d_raw[0]
    #                 tr.stats.sac={}
    #                 tr.stats.sac.evlo=evlo
    #                 tr.stats.sac.evla=evla
    #                 stla, elev, stlo=subdset.coordinates.values()
    #                 dist, az, baz=obspy.geodetics.gps2dist_azimuth(evla, evlo, stla, stlo) # distance is in m
    #                 distance = dist/1000.
    #                 tr.stats.sac.dist=distance
    #                 ntrace=ses3dtrace(tr.data, tr.stats)
    #                 try:
    #                     ab, Ms=ntrace.get_ms(Vgr=fieldpoint)
    #                 except:
    #                     continue
    #                 fieldpoint=Ms
    #             else:
    #                 stla, elev, stlo=self.waveforms[station_id].coordinates.values()
    #                 dist, az, baz=obspy.geodetics.gps2dist_azimuth(evla, evlo, stla, stlo) # distance is in m
    #                 distance = dist/1000.
    #             if distance == 0.:
    #                 continue
    #             FieldArr=np.append(FieldArr, stlo)
    #             FieldArr=np.append(FieldArr, stla)
    #             if fieldtype=='Vgr' or fieldtype=='Vph':
    #                 fieldpoint=distance/fieldpoint
    #             FieldArr=np.append(FieldArr, fieldpoint)
    #             if distflag:
    #                 FieldArr=np.append(FieldArr, distance)
    #             Nfp+=1
    #         if distflag:
    #             FieldArr=FieldArr.reshape( Nfp, 4)
    #         else:
    #             FieldArr=FieldArr.reshape( Nfp, 3)
    #         if outdir!=None:
    #             if not os.path.isdir(outdir):
    #                 os.makedirs(outdir)
    #             txtfname=outdir+'/'+tempdict[fieldtype]+'_'+str(per)+'.txt'
    #             header = 'evlo='+str(evlo)+' evla='+str(evla)
    #             np.savetxt( txtfname, FieldArr, fmt='%g', header=header )
    #         self.add_auxiliary_data(data=FieldArr, data_type='Field'+data_type, path=tempdict[fieldtype]+str(int(per)), parameters=outindex)
    #     return
    
            
def stack4mp(inv, datadir, outdir, ylst, mlst, pfx, fnametype):
    stackedST=[]
    cST=[]
    initflag=True
    channels1=inv.networks[0].stations[0].channels
    channels2=inv.networks[1].stations[0].channels
    netcode1=inv.networks[0].code
    stacode1=inv.networks[0].stations[0].code
    netcode2=inv.networks[1].code
    stacode2=inv.networks[1].stations[0].code
    mnumb=mlst.size
    for im in xrange(mnumb):
        skipflag=False
        for chan1 in channels1:
            if skipflag:
                break
            for chan2 in channels2:
                month=monthdict[mlst[im]]
                yrmonth=str(ylst[im])+'.'+month
                if fnametype==1:
                    fname=datadir+'/'+yrmonth+'/'+pfx+'/'+stacode1+'/'+pfx+'_'+stacode1+'_'+chan1.code+'_'+stacode2+'_'+chan2.code+'.SAC'
                elif fnametype==2:
                    fname=datadir+'/'+yrmonth+'/'+pfx+'/'+stacode1+'/'+pfx+'_'+stacode1+'_'+stacode2+'.SAC'
                if not os.path.isfile(fname):
                    skipflag=True
                    break
                try:
                    tr=obspy.core.read(fname)[0]
                except TypeError:
                    warnings.warn('Unable to read SAC for: ' + stacode1 +'_'+stacode2 +' Month: '+yrmonth, UserWarning, stacklevel=1)
                    skipflag=True
                if np.isnan(tr.data).any() or abs(tr.data.max())>1e20:
                    warnings.warn('NaN monthly SAC for: ' + stacode1 +'_'+stacode2 +' Month: '+yrmonth, UserWarning, stacklevel=1)
                    skipflag=True
                    break
                cST.append(tr)
        if len(cST)!=len(channels1)*len(channels2) or skipflag:
            cST=[]
            continue
        if initflag:
            stackedST=copy.deepcopy(cST)
            initflag=False
        else:
            for itr in xrange(len(cST)):
                mtr=cST[itr]
                stackedST[itr].data+=mtr.data
                stackedST[itr].stats.sac.user0+=mtr.stats.sac.user0
        cST=[]
    if len(stackedST)==len(channels1)*len(channels2):
        print 'Finished Stacking for:'+stacode1+'_'+stacode2
        i=0
        for chan1 in channels1:
            for chan2 in channels2:
                stackedTr=stackedST[i]
                outfname=outdir+'/'+pfx+'/'+netcode1+'.'+stacode1+'/'+ \
                    pfx+'_'+netcode1+'.'+stacode1+'_'+chan1.code+'_'+netcode2+'.'+stacode2+'_'+chan2.code+'.SAC'
                stackedTr.write(outfname, format='SAC')
                i+=1
    return

def aftan4mp(aTr, outdir, inftan, prephdir, f77, pfx):
    print 'aftan analysis for: '+ aTr.stats.sac.kuser0+'.'+aTr.stats.sac.kevnm+'_'+chan1+'_'+aTr.stats.network+'.'+aTr.stats.station+'_'+chan2
    if prephdir !=None:
        phvelname = prephdir + "/%s.%s.pre" %(aTr.stats.sac.kuser0+'.'+aTr.stats.sac.kevnm, aTr.stats.network+'.'+aTr.stats.station)
    else:
        phvelname =''
    if abs(aTr.stats.sac.b+aTr.stats.sac.e)< aTr.stats.delta:
        aTr.makesym()
    if f77:
        aTr.aftanf77(pmf=inftan.pmf, piover4=inftan.piover4, vmin=inftan.vmin, vmax=inftan.vmax, tmin=inftan.tmin, tmax=inftan.tmax,
            tresh=inftan.tresh, ffact=inftan.ffact, taperl=inftan.taperl, snr=inftan.snr, fmatch=inftan.fmatch, nfin=inftan.nfin,
                npoints=inftan.npoints, perc=inftan.perc, phvelname=phvelname)
    else:
        aTr.aftan(pmf=inftan.pmf, piover4=inftan.piover4, vmin=inftan.vmin, vmax=inftan.vmax, tmin=inftan.tmin, tmax=inftan.tmax,
            tresh=inftan.tresh, ffact=inftan.ffact, taperl=inftan.taperl, snr=inftan.snr, fmatch=inftan.fmatch, nfin=inftan.nfin,
                npoints=inftan.npoints, perc=inftan.perc, phvelname=phvelname)
    aTr.get_snr(ffact=inftan.ffact) # SNR analysis
    chan1=aTr.stats.sac.kcmpnm[:3]
    chan2=aTr.stats.sac.kcmpnm[3:]
    foutPR=outdir+'/'+pfx+'/'+aTr.stats.sac.kuser0+'.'+aTr.stats.sac.kevnm+'/'+ \
                pfx+'_'+aTr.stats.sac.kuser0+'.'+aTr.stats.sac.kevnm+'_'+chan1+'_'+aTr.stats.network+'.'+aTr.stats.station+'_'+chan2+'.SAC'
    aTr.ftanparam.writeDISPbinary(foutPR)
    return
    
    