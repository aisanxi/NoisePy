# -*- coding: utf-8 -*-
"""
A python module for earthquake data analysis based on ASDF database

:Methods:
    aftan analysis (use pyaftan or aftanf77)
    Automatic Receiver Function Analysis( Iterative Deconvolution and Harmonic Stripping )
    Preparing data for surface wave tomography (Barmin's method, Eikonal/Helmholtz tomography)

:Dependencies:
    pyasdf and its dependencies
    ObsPy  and its dependencies
    pyproj
    Basemap
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
import matplotlib.dates as mdates
import obspy
import warnings
import copy
import os, shutil
from functools import partial
import multiprocessing
import pyaftan
from subprocess import call
from obspy.clients.fdsn.client import Client
from mpl_toolkits.basemap import Basemap, shiftgrid, cm
import obspy.signal.array_analysis
from obspy.imaging.cm import obspy_sequential
from pyproj import Geod
from obspy.taup import TauPyModel
import CURefPy
import glob

sta_info_default    = {'xcorr': 1, 'isnet': 0}
ref_header_default  = {'otime': '', 'network': '', 'station': '', 'stla': 12345, 'stlo': 12345, 'evla': 12345, 'evlo': 12345, 'evdp': 0.,
                        'dist': 0., 'az': 12345, 'baz': 12345, 'delta': 12345, 'npts': 12345, 'b': 12345, 'e': 12345, 'arrival': 12345, 'phase': '',
                        'tbeg': 12345, 'tend': 12345, 'hslowness': 12345, 'ghw': 12345, 'VR':  12345, 'moveout': -1}
monthdict           = {1: 'JAN', 2: 'FEB', 3: 'MAR', 4: 'APR', 5: 'MAY', 6: 'JUN', 7: 'JUL', 8: 'AUG', 9: 'SEP', 10: 'OCT', 11: 'NOV', 12: 'DEC'}
geodist             = Geod(ellps='WGS84')
taupmodel           = TauPyModel(model="iasp91")
    
class requestInfo(object):
    def __init__(self, evnumb, network, station, location, channel, starttime, endtime, quality=None,
            minimumlength=None, longestonly=None, filename=None, attach_response=False, baz=0):
        self.evnumb         = evnumb
        self.network        = network
        self.station        = station
        self.location       = location
        self.channel        = channel
        self.starttime      = starttime
        self.endtime        = endtime
        self.quality        = quality
        self.minimumlength  = minimumlength
        self.longestonly    = longestonly
        self.filename       = filename
        self.attach_response= attach_response
        self.baz            = baz

class quakeASDF(pyasdf.ASDFDataSet):
    """ An object to for earthquake data analysis based on ASDF database
    """
    
    def print_info(self):
        """
        Print information of the dataset.
        =================================================================================================================
        Version History:
            Dec 8th, 2016   - first version
        =================================================================================================================
        """
        outstr  = '============================================================ Earthquake Database ===========================================================\n'
        outstr  += self.__str__()+'\n'
        outstr  += '--------------------------------------------------------- Surface wave auxiliary Data ------------------------------------------------------\n'
        if 'DISPbasic1' in self.auxiliary_data.list():
            outstr      += 'DISPbasic1              - Basic dispersion curve, no jump correction\n'
        if 'DISPbasic2' in self.auxiliary_data.list():
            outstr      += 'DISPbasic2              - Basic dispersion curve, with jump correction\n'
        if 'DISPpmf1' in self.auxiliary_data.list():
            outstr      += 'DISPpmf1                - PMF dispersion curve, no jump correction\n'
        if 'DISPpmf2' in self.auxiliary_data.list():
            outstr      += 'DISPpmf2                - PMF dispersion curve, with jump correction\n'
        if 'DISPbasic1interp' in self.auxiliary_data.list():
            outstr      += 'DISPbasic1interp        - Interpolated DISPbasic1\n'
        if 'DISPbasic2interp' in self.auxiliary_data.list():
            outstr      += 'DISPbasic2interp        - Interpolated DISPbasic2\n'
        if 'DISPpmf1interp' in self.auxiliary_data.list():
            outstr      += 'DISPpmf1interp          - Interpolated DISPpmf1\n'
        if 'DISPpmf2interp' in self.auxiliary_data.list():
            outstr      += 'DISPpmf2interp          - Interpolated DISPpmf2\n'
        if 'FieldDISPbasic1interp' in self.auxiliary_data.list():
            outstr      += 'FieldDISPbasic1interp   - Field data of DISPbasic1\n'
        if 'FieldDISPbasic2interp' in self.auxiliary_data.list():
            outstr      += 'FieldDISPbasic2interp   - Field data of DISPbasic2\n'
        if 'FieldDISPpmf1interp' in self.auxiliary_data.list():
            outstr      += 'FieldDISPpmf1interp     - Field data of DISPpmf1\n'
        if 'FieldDISPpmf2interp' in self.auxiliary_data.list():
            outstr      += 'FieldDISPpmf2interp     - Field data of DISPpmf2\n'
        outstr  += '------------------------------------------------------ Receiver function auxiliary Data ----------------------------------------------------\n'
        if 'RefR' in self.auxiliary_data.list():
            outstr      += 'RefR                    - Radial receiver function\n'
        if 'RefRHS' in self.auxiliary_data.list():
            outstr      += 'RefRHS                  - Harmonic stripping results of radial receiver function\n'
        if 'RefRmoveout' in self.auxiliary_data.list():
            outstr      += 'RefRmoveout             - Move out of radial receiver function\n'
        if 'RefRscaled' in self.auxiliary_data.list():
            outstr      += 'RefRscaled              - Scaled radial receiver function\n'
        if 'RefRstreback' in self.auxiliary_data.list():
            outstr      += 'RefRstreback            - Stretch back of radial receiver function\n'
        outstr  += '============================================================================================================================================\n'
        print outstr
        return
    
    def get_events(self, startdate, enddate, add2dbase=True, gcmt=False, Mmin=5.5, Mmax=None, minlatitude=None, maxlatitude=None, minlongitude=None, maxlongitude=None,
            latitude=None, longitude=None, minradius=None, maxradius=None, mindepth=None, maxdepth=None, magnitudetype=None,
            outquakeml=None):
        """Get earthquake catalog from IRIS server
        =======================================================================================================
        ::: input parameters :::
        startdate, enddata  - start/end date for searching
        Mmin, Mmax          - minimum/maximum magnitude for searching                
        minlatitude         - Limit to events with a latitude larger than the specified minimum.
        maxlatitude         - Limit to events with a latitude smaller than the specified maximum.
        minlongitude        - Limit to events with a longitude larger than the specified minimum.
        maxlongitude        - Limit to events with a longitude smaller than the specified maximum.
        latitude            - Specify the latitude to be used for a radius search.
        longitude           - Specify the longitude to the used for a radius search.
        minradius           - Limit to events within the specified minimum number of degrees from the
                                geographic point defined by the latitude and longitude parameters.
        maxradius           - Limit to events within the specified maximum number of degrees from the
                                geographic point defined by the latitude and longitude parameters.
        mindepth            - Limit to events with depth, in kilometers, larger than the specified minimum.
        maxdepth            - Limit to events with depth, in kilometers, smaller than the specified maximum.
        magnitudetype       - Specify a magnitude type to use for testing the minimum and maximum limits.
        =======================================================================================================
        """
        starttime   = obspy.core.utcdatetime.UTCDateTime(startdate)
        endtime     = obspy.core.utcdatetime.UTCDateTime(enddate)
        if not gcmt:
            client  = Client('IRIS')
            try:
                catISC      = client.get_events(starttime=starttime, endtime=endtime, minmagnitude=Mmin, maxmagnitude=Mmax, catalog='ISC',
                                minlatitude=minlatitude, maxlatitude=maxlatitude, minlongitude=minlongitude, maxlongitude=maxlongitude,
                                latitude=latitude, longitude=longitude, minradius=minradius, maxradius=maxradius, mindepth=mindepth,
                                maxdepth=maxdepth, magnitudetype=magnitudetype)
                endtimeISC  = catISC[0].origins[0].time
            except:
                catISC      = obspy.core.event.Catalog()
                endtimeISC  = starttime
            if endtime.julday-endtimeISC.julday >1:
                try:
                    catPDE  = client.get_events(starttime=endtimeISC, endtime=endtime, minmagnitude=Mmin, maxmagnitude=Mmax, catalog='NEIC PDE',
                                minlatitude=minlatitude, maxlatitude=maxlatitude, minlongitude=minlongitude, maxlongitude=maxlongitude,
                                latitude=latitude, longitude=longitude, minradius=minradius, maxradius=maxradius, mindepth=mindepth,
                                maxdepth=maxdepth, magnitudetype=magnitudetype)
                    catalog = catISC+catPDE
                except:
                    catalog = catISC
            else:
                catalog     = catISC
            outcatalog      = obspy.core.event.Catalog()
            # check magnitude
            for event in catalog:
                if event.magnitudes[0].mag < Mmin:
                    continue
                outcatalog.append(event)
        else:
            gcmt_url_old    = 'http://www.ldeo.columbia.edu/~gcmt/projects/CMT/catalog/jan76_dec13.ndk'
            gcmt_new        = 'http://www.ldeo.columbia.edu/~gcmt/projects/CMT/catalog/NEW_MONTHLY'
            if starttime.year < 2005:
                print('Loading catalog: '+gcmt_url_old)
                cat_old     = obspy.read_events(gcmt_url_old)
                if Mmax != None:
                    cat_old = cat_old.filter("magnitude <= %g" %Mmax)
                if maxlongitude != None:
                    cat_old = cat_old.filter("longitude <= %g" %maxlongitude)
                if minlongitude != None:
                    cat_old = cat_old.filter("longitude >= %g" %minlongitude)
                if maxlatitude != None:
                    cat_old = cat_old.filter("latitude <= %g" %maxlatitude)
                if minlatitude != None:
                    cat_old = cat_old.filter("latitude >= %g" %minlatitude)
                if maxdepth != None:
                    cat_old = cat_old.filter("depth <= %g" %(maxdepth*1000.))
                if mindepth != None:
                    cat_old = cat_old.filter("depth >= %g" %(mindepth*1000.))
                temp_stime  = obspy.core.utcdatetime.UTCDateTime('2014-01-01')
                outcatalog  = cat_old.filter("magnitude >= %g" %Mmin, "time >= %s" %str(starttime), "time <= %s" %str(endtime) )
            else:
                outcatalog      = obspy.core.event.Catalog()
                temp_stime      = copy.deepcopy(starttime)
                temp_stime.day  = 1
            while (temp_stime < endtime):
                year            = temp_stime.year
                month           = temp_stime.month
                yearstr         = str(int(year))[2:]
                monstr          = monthdict[month]
                monstr          = monstr.lower()
                if year==2005 and month==6:
                    monstr      = 'june'
                if year==2005 and month==7:
                    monstr      = 'july'
                if year==2005 and month==9:
                    monstr      = 'sept'
                gcmt_url_new    = gcmt_new+'/'+str(int(year))+'/'+monstr+yearstr+'.ndk'
                # cat_new     = obspy.core.event.read_events(gcmt_url_new)
                try:
                    cat_new     = obspy.read_events(gcmt_url_new)
                    print('Loading catalog: '+gcmt_url_new)
                except:
                    print('Link not found: '+gcmt_url_new)
                    break
                cat_new         = cat_new.filter("magnitude >= %g" %Mmin, "time >= %s" %str(starttime), "time <= %s" %str(endtime) )
                if Mmax != None:
                    cat_new     = cat_new.filter("magnitude <= %g" %Mmax)
                if maxlongitude != None:
                    cat_new     = cat_new.filter("longitude <= %g" %maxlongitude)
                if minlongitude!=None:
                    cat_new     = cat_new.filter("longitude >= %g" %minlongitude)
                if maxlatitude!=None:
                    cat_new     = cat_new.filter("latitude <= %g" %maxlatitude)
                if minlatitude!=None:
                    cat_new     = cat_new.filter("latitude >= %g" %minlatitude)
                if maxdepth != None:
                    cat_new     = cat_new.filter("depth <= %g" %(maxdepth*1000.))
                if mindepth != None:
                    cat_new     = cat_new.filter("depth >= %g" %(mindepth*1000.))
                outcatalog      += cat_new
                try:
                    temp_stime.month    +=1
                except:
                    temp_stime.year     +=1
                    temp_stime.month    = 1
        try:
            self.cat    += outcatalog
        except:
            self.cat    = outcatalog
        if add2dbase:
            self.add_quakeml(outcatalog)
        if outquakeml != None:
            self.cat.write(outquakeml, format='quakeml')
        return
    
    
    
    def read_quakeml(self, inquakeml, add2dbase=False):
        self.cat    = obspy.read_events(inquakeml)
        if add2dbase:
            self.add_quakeml(self.cat)
        return
    
    def copy_catalog(self):
        print('Copying catalog from ASDF to memory')
        self.cat    = self.events.copy()
    
    def read_stationtxt(self, stafile, source='CIEI', chans=['BHZ', 'BHE', 'BHN']):
        """Read txt station list 
        """
        sta_info    = sta_info_default.copy()
        with open(stafile, 'r') as f:
            Sta                     = []
            site                    = obspy.core.inventory.util.Site(name='01')
            creation_date           = obspy.core.utcdatetime.UTCDateTime(0)
            inv                     = obspy.core.inventory.inventory.Inventory(networks=[], source=source)
            total_number_of_channels= len(chans)
            for lines in f.readlines():
                lines       = lines.split()
                netsta      = lines[0]
                netcode     = netsta[:2]
                stacode     = netsta[2:]
                if stacode[-1]=='/':
                    stacode = stacode[:-1]
                    print netcode, stacode
                lon         = float(lines[1])
                lat         = float(lines[2])
                if lat>90.:
                    lon     = float(lines[2])
                    lat     = float(lines[1])
                netsta      = netcode+'.'+stacode
                if Sta.__contains__(netsta):
                    index   = Sta.index(netsta)
                    if abs(self[index].lon-lon) >0.01 and abs(self[index].lat-lat) >0.01:
                        raise ValueError('Incompatible Station Location:' + netsta+' in Station List!')
                    else:
                        print 'Warning: Repeated Station:' +netsta+' in Station List!'
                        continue
                channels    = []
                if lon>180.:
                    lon -= 360.
                for chan in chans:
                    channel = obspy.core.inventory.channel.Channel(code=chan, location_code='01', latitude=lat, longitude=lon,
                                elevation=0.0, depth=0.0)
                    channels.append(channel)
                station     = obspy.core.inventory.station.Station(code=stacode, latitude=lat, longitude=lon, elevation=0.0,
                                site=site, channels=channels, total_number_of_channels = total_number_of_channels, creation_date = creation_date)
                network     = obspy.core.inventory.network.Network(code=netcode, stations=[station])
                networks    = [network]
                inv         += obspy.core.inventory.inventory.Inventory(networks=networks, source=source)
        print 'Writing obspy inventory to ASDF dataset'
        self.add_stationxml(inv)
        print 'End writing obspy inventory to ASDF dataset'
        return
    
    def read_sac(self, datadir):
        """This function is a scratch for reading a specific datasets, DO NOT use this function!
        """
        L       = len(self.events)
        evnumb  = 0
        import glob
        for event in self.events:
            event_id        = event.resource_id.id.split('=')[-1]
            magnitude       = event.magnitudes[0].mag; Mtype=event.magnitudes[0].magnitude_type
            event_descrip   = event.event_descriptions[0].text+', '+event.event_descriptions[0].type
            evnumb          +=1
            print '================================= Getting surface wave data ==================================='
            print 'Event ' + str(evnumb)+' : '+event_descrip+', '+Mtype+' = '+str(magnitude) 
            st              = obspy.Stream()
            otime           = event.origins[0].time
            evlo            = event.origins[0].longitude; evla=event.origins[0].latitude
            tag             = 'surf_ev_%05d' %evnumb
            # if lon0!=None and lat0!=None:
            #     dist, az, baz=obspy.geodetics.gps2dist_azimuth(evla, evlo, lat0, lon0) # distance is in m
            #     dist=dist/1000.
            #     starttime=otime+dist/vmax; endtime=otime+dist/vmin
            #     commontime=True
            # else:
            #     commontime=False
            odate           = str(otime.year)+'%02d' %otime.month +'%02d' %otime.day
            for staid in self.waveforms.list():
                netcode, stacode=staid.split('.')
                print staid
                stla, elev, stlo=self.waveforms[staid].coordinates.values()
                # sta_datadir=datadir+'/'+netcode+'/'+stacode
                sta_datadir=datadir+'/'+netcode+'/'+stacode
                sacpfx=sta_datadir+'/'+stacode+'.'+odate
                
                pzpfx='/home/lili/code/china_data/response_files/SAC_*'+netcode+'_'+stacode
                respfx='/home/lili/code/china_data/RESP4WeisenCUB/dbRESPCNV20131007/'+netcode+'/'+staid+'/RESP.'+staid
                st=obspy.Stream()
                for chan in ['*Z', '*E', '*N']:
                    sacfname    = sacpfx+chan
                    pzfpattern  = pzpfx+'_'+chan
                    respfpattern= respfx+'*BH'+chan[-1]+'*'
                    #################
                    try: respfname=glob.glob(respfpattern)[0]
                    except: break
                    seedresp = {'filename': respfname,  # RESP filename
                    # when using Trace/Stream.simulate() the "date" parameter can
                    # also be omitted, and the starttime of the trace is then used.
                    # Units to return response in ('DIS', 'VEL' or ACC)
                    'units': 'VEL'
                    }
                    try: tr=obspy.read(sacfname)[0]
                    except: break
                    tr.detrend()
                    tr.stats.channel='BH'+chan[-1]
                    tr.simulate(paz_remove=None, pre_filt=(0.001, 0.005, 1, 100.0), seedresp=seedresp)
                    ################
                    # try: pzfname = glob.glob(pzfpattern)[0]
                    # except: break
                    # try: tr=obspy.read(sacfname)[0]
                    # except: break
                    # obspy.io.sac.sacpz.attach_paz(tr, pzfname)
                    # tr.decimate(10)
                    # tr.detrend()
                    # tr.simulate(paz_remove=tr.stats.paz, pre_filt=(0.001, 0.005, 1, 100.0))
                    st.append(tr)
                self.add_waveforms(st, event_id=event_id, tag=tag)    
    
    def _get_basemap(self, projection='lambert', geopolygons=None, resolution='i'):
        """Get basemap for plotting results
        """
        # fig=plt.figure(num=None, figsize=(12, 12), dpi=80, facecolor='w', edgecolor='k')
        lat_centre  = (self.maxlat+self.minlat)/2.0
        lon_centre  = (self.maxlon+self.minlon)/2.0
        if projection=='merc':
            m       = Basemap(projection='merc', llcrnrlat=self.minlat-5., urcrnrlat=self.maxlat+5., llcrnrlon=self.minlon-5.,
                        urcrnrlon=self.maxlon+5., lat_ts=20, resolution=resolution)
            m.drawparallels(np.arange(-80.0,80.0,5.0), labels=[1,0,0,1])
            m.drawmeridians(np.arange(-170.0,170.0,5.0), labels=[1,0,0,1])
            m.drawstates(color='g', linewidth=2.)
        elif projection=='global':
            m       = Basemap(projection='ortho',lon_0=lon_centre, lat_0=lat_centre, resolution=resolution)
            m.drawparallels(np.arange(-80.0,80.0,10.0), labels=[1,0,0,1])
            m.drawmeridians(np.arange(-170.0,170.0,10.0), labels=[1,0,0,1])
        elif projection=='regional_ortho':
            m1      = Basemap(projection='ortho', lon_0=self.minlon, lat_0=self.minlat, resolution='l')
            m       = Basemap(projection='ortho', lon_0=self.minlon, lat_0=self.minlat, resolution=resolution,\
                        llcrnrx=0., llcrnry=0., urcrnrx=m1.urcrnrx/mapfactor, urcrnry=m1.urcrnry/3.5)
            m.drawparallels(np.arange(-80.0,80.0,10.0), labels=[1,0,0,0],  linewidth=2,  fontsize=20)
            m.drawmeridians(np.arange(-170.0,170.0,10.0),  linewidth=2)
        elif projection=='lambert':
            distEW, az, baz = obspy.geodetics.gps2dist_azimuth(self.minlat, self.minlon, self.minlat, self.maxlon) # distance is in m
            distNS, az, baz = obspy.geodetics.gps2dist_azimuth(self.minlat, self.minlon, self.maxlat+2., self.minlon) # distance is in m
            m       = Basemap(width=distEW, height=distNS, rsphere=(6378137.00,6356752.3142), resolution='l', projection='lcc',\
                        lat_1=self.minlat, lat_2=self.maxlat, lon_0=lon_centre, lat_0=lat_centre+1)
            m.drawparallels(np.arange(-80.0,80.0,10.0), linewidth=1, dashes=[2,2], labels=[1,1,0,0], fontsize=15)
            m.drawmeridians(np.arange(-170.0,170.0,10.0), linewidth=1, dashes=[2,2], labels=[0,0,1,0], fontsize=15)
        m.drawcoastlines(linewidth=1.0)
        m.drawcountries(linewidth=1.)
        m.fillcontinents(lake_color='#99ffff',zorder=0.2)
        m.drawmapboundary(fill_color="white")
        m.drawstates()
        try:
            geopolygons.PlotPolygon(inbasemap=m)
        except:
            pass
        return m
    
    def plot_events(self, gcmt=False, projection='lambert', valuetype='depth', geopolygons=None, showfig=True, vmin=None, vmax=None):
        if gcmt:
            from obspy.imaging.beachball import beach
            ax  = plt.gca()
        evlons  = np.array([])
        evlats  = np.array([])
        values  = np.array([])
        focmecs = []
        for event in self.events:
            event_id    = event.resource_id.id.split('=')[-1]
            magnitude   = event.magnitudes[0].mag
            Mtype       = event.magnitudes[0].magnitude_type
            otime       = event.origins[0].time
            evlo        = event.origins[0].longitude
            evla        = event.origins[0].latitude
            evdp        = event.origins[0].depth/1000.
            if evlo > -80.:
                continue
            evlons      = np.append(evlons, evlo)
            evlats      = np.append(evlats, evla);
            if valuetype=='depth':
                values  = np.append(values, evdp)
            elif valuetype=='mag':
                values  = np.append(values, magnitude)
            if gcmt:
                mtensor = event.focal_mechanisms[0].moment_tensor.tensor
                mt      = [mtensor.m_rr, mtensor.m_tt, mtensor.m_pp, mtensor.m_rt, mtensor.m_rp, mtensor.m_tp]
                # nodalP=event.focal_mechanisms[0].nodal_planes.values()[1]
                # mt=[nodalP.strike, nodalP.dip, nodalP.rake]
                focmecs.append(mt)
        self.minlat     = evlats.min()-1.; self.maxlat=evlats.max()+1.
        self.minlon     = evlons.min()-1.; self.maxlon=evlons.max()+1.
        # self.minlat=15; self.maxlat=50
        # self.minlon=95; self.maxlon=128
        m               = self._get_basemap(projection=projection, geopolygons=geopolygons)
        import pycpt
        cmap            = pycpt.load.gmtColormap('./GMT_panoply.cpt')
        # cmap =discrete_cmap(int((vmax-vmin)/0.1)+1, cmap)
        x, y            = m(evlons, evlats)
        if vmax==None and vmin==None:
            vmax        = values.max()
            vmin        = values.min()
        if gcmt:
            for i in xrange(len(focmecs)):
                value   = values[i]
                rgbcolor= cmap( (value-vmin)/(vmax-vmin) )
                b       = beach(focmecs[i], xy=(x[i], y[i]), width=100000, linewidth=1, facecolor=rgbcolor)
                b.set_zorder(10)
                ax.add_collection(b)
                # ax.annotate(str(i), (x[i]+50000, y[i]+50000))
            im          = m.scatter(x, y, marker='o', s=1, c=values, cmap=cmap, vmin=vmin, vmax=vmax)
            cb          = m.colorbar(im, "bottom", size="3%", pad='2%')
            cb.set_label(valuetype, fontsize=20)
        else:
            if values.size!=0:
                im      = m.scatter(x, y, marker='o', s=300, c=values, cmap=cmap, vmin=vmin, vmax=vmax)
                cb      = m.colorbar(im, "bottom", size="3%", pad='2%')
            else:
                m.plot(x,y,'o')
        if gcmt:
            stime       = self.events[0].origins[0].time
            etime       = self.events[-1].origins[0].time
        else:
            etime       = self.events[0].origins[0].time
            stime       = self.events[-1].origins[0].time
        plt.suptitle('Number of event: '+str(len(self.events))+' time range: '+str(stime)+' - '+str(etime), fontsize=20 )
        if showfig:
            plt.show()
        return   
    
    def get_stations(self, startdate=None, enddate=None, network=None, station=None, location=None, channel=None, includerestricted=False,
            minlatitude=None, maxlatitude=None, minlongitude=None, maxlongitude=None, latitude=None, longitude=None, minradius=None, maxradius=None):
        """Get station inventory from IRIS server
        =======================================================================================================
        ::: input parameters :::
        startdate, enddata  - start/end date for searching
        network             - Select one or more network codes.
                                Can be SEED network codes or data center defined codes.
                                    Multiple codes are comma-separated (e.g. "IU,TA").
        station             - Select one or more SEED station codes.
                                Multiple codes are comma-separated (e.g. "ANMO,PFO").
        location            - Select one or more SEED location identifiers.
                                Multiple identifiers are comma-separated (e.g. "00,01").
                                As a special case “--“ (two dashes) will be translated to a string of two space
                                characters to match blank location IDs.
        channel             - Select one or more SEED channel codes.
                                Multiple codes are comma-separated (e.g. "BHZ,HHZ").             
        minlatitude         - Limit to events with a latitude larger than the specified minimum.
        maxlatitude         - Limit to events with a latitude smaller than the specified maximum.
        minlongitude        - Limit to events with a longitude larger than the specified minimum.
        maxlongitude        - Limit to events with a longitude smaller than the specified maximum.
        latitude            - Specify the latitude to be used for a radius search.
        longitude           - Specify the longitude to the used for a radius search.
        minradius           - Limit to events within the specified minimum number of degrees from the
                                geographic point defined by the latitude and longitude parameters.
        maxradius           - Limit to events within the specified maximum number of degrees from the
                                geographic point defined by the latitude and longitude parameters.
        =======================================================================================================
        """
        try:
            starttime   = obspy.core.utcdatetime.UTCDateTime(startdate)
        except:
            starttime   = None
        try:
            endtime     = obspy.core.utcdatetime.UTCDateTime(enddate)
        except:
            endtime     = None
        client          = Client('IRIS')
        inv             = client.get_stations(network=network, station=station, starttime=starttime, endtime=endtime, channel=channel, 
                            minlatitude=minlatitude, maxlatitude=maxlatitude, minlongitude=minlongitude, maxlongitude=maxlongitude,
                            latitude=latitude, longitude=longitude, minradius=minradius, maxradius=maxradius, level='channel',
                            includerestricted=includerestricted)
        self.add_stationxml(inv)
        try:
            self.inv    +=inv
        except:
            self.inv    = inv
        return 
    
    def get_surf_waveforms(self, lon0=None, lat0=None, minDelta=-1, maxDelta=181, channel='LHZ', vmax=6.0, vmin=1.0, verbose=False,
                            startdate=None, enddate=None ):
        """Get surface wave data from IRIS server
        ====================================================================================================================
        ::: input parameters :::
        lon0, lat0      - center of array. If specified, all waveform will have the same starttime and endtime
        min/maxDelta    - minimum/maximum epicentral distance, in degree
        channel         - Channel code, e.g. 'BHZ'.
                            Last character (i.e. component) can be a wildcard (‘?’ or ‘*’) to fetch Z, N and E component.
        vmin, vmax      - minimum/maximum velocity for surface wave window
        =====================================================================================================================
        """
        client              = Client('IRIS')
        evnumb              = 0
        L                   = len(self.events)
        try:
            stime4down  = obspy.core.utcdatetime.UTCDateTime(startdate)
        except:
            stime4down  = obspy.UTCDateTime(0)
        try:
            etime4down  = obspy.core.utcdatetime.UTCDateTime(enddate)
        except:
            etime4down  = obspy.UTCDateTime()
        try:
            print self.cat
        except AttributeError:
            self.copy_catalog()
        for event in self.cat:
            event_id        = event.resource_id.id.split('=')[-1]
            magnitude       = event.magnitudes[0].mag
            Mtype           = event.magnitudes[0].magnitude_type
            event_descrip   = event.event_descriptions[0].text+', '+event.event_descriptions[0].type
            otime           = event.origins[0].time
            evlo            = event.origins[0].longitude
            evla            = event.origins[0].latitude
            evnumb          +=1
            if otime < stime4down or otime > etime4down:
                continue
            print('================================= Getting surface wave data ===================================')
            print('Event ' + str(evnumb)+' : '+event_descrip+', '+Mtype+' = '+str(magnitude))
            st              = obspy.Stream()
            if lon0!=None and lat0!=None:
                dist, az, baz   = obspy.geodetics.gps2dist_azimuth(evla, evlo, lat0, lon0) # distance is in m
                dist            = dist/1000.
                starttime       = otime+dist/vmax
                endtime         = otime+dist/vmin
                commontime      = True
            else:
                commontime      = False
            for staid in self.waveforms.list():
                netcode, stacode= staid.split('.')
                stla, elev, stlo= self.waveforms[staid].coordinates.values()
                if not commontime:
                    dist, az, baz   = obspy.geodetics.gps2dist_azimuth(evla, evlo, stla, stlo) # distance is in m
                    dist            = dist/1000.
                    Delta           = obspy.geodetics.kilometer2degrees(dist)
                    if Delta<minDelta:
                        continue
                    if Delta>maxDelta:
                        continue
                    starttime       = otime+dist/vmax
                    endtime         = otime+dist/vmin
                # location=self.waveforms[staid].StationXML[0].stations[0].channels[0].location_code
                try:
                    # st += client.get_waveforms(network=netcode, station=stacode, location=location, channel=channel,
                    #         starttime=starttime, endtime=endtime, attach_response=True)
                    st              += client.get_waveforms(network=netcode, station=stacode, location='00', channel=channel,
                                        starttime=starttime, endtime=endtime, attach_response=True)
                except:
                    if verbose:
                        print 'No data for:', staid
                    continue
                if verbose:
                    print 'Getting data for:', staid
            print('===================================== Removing response =======================================')
            pre_filt    = (0.001, 0.005, 1, 100.0)
            st.detrend()
            st.remove_response(pre_filt=pre_filt, taper_fraction=0.1)
            tag         = 'surf_ev_%05d' %evnumb
            # adding waveforms
            self.add_waveforms(st, event_id=event_id, tag=tag)
        return
    
    def get_surf_waveforms_mp(self, outdir, lon0=None, lat0=None, minDelta=-1, maxDelta=181, channel='LHZ', vmax=6.0, vmin=1.0, verbose=False,
            subsize=1000, deletemseed=False, nprocess=None, snumb=0, enumb=None, startdate=None, enddate=None):
        """Get surface wave data from IRIS server with multiprocessing
        ====================================================================================================================
        ::: input parameters :::
        lon0, lat0      - center of array. If specified, all wave form will have the same starttime and endtime
        min/maxDelta    - minimum/maximum epicentral distance, in degree
        channel         - Channel code, e.g. 'BHZ'.
                            Last character (i.e. component) can be a wildcard (‘?’ or ‘*’) to fetch Z, N and E component.
        vmin, vmax      - minimum/maximum velocity for surface wave window
        subsize         - subsize of processing list, use to prevent lock in multiprocessing process
        deletemseed     - delete output MiniSeed files
        nprocess        - number of processes
        snumb, enumb    - start/end number of processing block
        =====================================================================================================================
        """
        client      = Client('IRIS')
        evnumb      = 0
        L           = len(self.events)
        if not os.path.isdir(outdir):
            os.makedirs(outdir)
        reqwaveLst  = []
        swave       = snumb*subsize
        iwave       = 0
        try:
            stime4down  = obspy.core.utcdatetime.UTCDateTime(startdate)
        except:
            stime4down  = obspy.UTCDateTime(0)
        try:
            etime4down  = obspy.core.utcdatetime.UTCDateTime(enddate)
        except:
            etime4down  = obspy.UTCDateTime()
        print('================================= Preparing for surface wave data download ===================================')
        try:
            print self.cat
        except AttributeError:
            self.copy_catalog()
        for event in self.cat:
            eventid         = event.resource_id.id.split('=')[-1]
            magnitude       = event.magnitudes[0].mag
            Mtype           = event.magnitudes[0].magnitude_type
            event_descrip   = event.event_descriptions[0].text+', '+event.event_descriptions[0].type
            evnumb          +=1
            otime           = event.origins[0].time
            evlo            = event.origins[0].longitude
            evla            = event.origins[0].latitude
            if otime < stime4down or otime > etime4down:
                continue
            if lon0!=None and lat0!=None:
                dist, az, baz   = obspy.geodetics.gps2dist_azimuth(evla, evlo, lat0, lon0) # distance is in m
                dist            = dist/1000.
                starttime       = otime+dist/vmax
                endtime         = otime+dist/vmin
                commontime      = True
            else:
                commontime      = False
            for staid in self.waveforms.list():
                netcode, stacode= staid.split('.')
                iwave           += 1
                if iwave < swave:
                    continue
                stla, elev, stlo    = self.waveforms[staid].coordinates.values()
                if not commontime:
                    dist, az, baz   = obspy.geodetics.gps2dist_azimuth(evla, evlo, stla, stlo) # distance is in m
                    dist            = dist/1000.
                    Delta           = obspy.geodetics.kilometer2degrees(dist)
                    if Delta<minDelta:
                        continue
                    if Delta>maxDelta:
                        continue
                    starttime       = otime+dist/vmax
                    endtime         = otime+dist/vmin
                location            = self.waveforms[staid].StationXML[0].stations[0].channels[0].location_code
                reqwaveLst.append( requestInfo(evnumb=evnumb, network=netcode, station=stacode, location=location, channel=channel,
                            starttime=starttime, endtime=endtime, attach_response=True) )
        print('============================= Start multiprocessing download surface wave data ===============================')
        if len(reqwaveLst) > subsize:
            Nsub            = int(len(reqwaveLst)/subsize)
            # if enumb==None: enumb=Nsub
            for isub in range(Nsub):
                # if isub < snumb: continue
                # if isub > enumb: continue
                print 'Subset:', isub+1,'in',Nsub,'sets'
                creqlst     = reqwaveLst[isub*subsize:(isub+1)*subsize]
                GETDATA     = partial(get_waveforms4mp, outdir=outdir, client=client, pre_filt = (0.001, 0.005, 1, 100.0), verbose=verbose, rotation=False)
                pool        = multiprocessing.Pool(processes=nprocess)
                pool.map(GETDATA, creqlst) #make our results with a map call
                pool.close() #we are not adding any more processes
                pool.join() #tell it to wait until all threads are done before going on
            creqlst         = reqwaveLst[(isub+1)*subsize:]
            GETDATA         = partial(get_waveforms4mp, outdir=outdir, client=client, pre_filt = (0.001, 0.005, 1, 100.0), verbose=verbose, rotation=False)
            pool            = multiprocessing.Pool(processes=nprocess)
            pool.map(GETDATA, creqlst) #make our results with a map call
            pool.close() #we are not adding any more processes
            pool.join() #tell it to wait until all threads are done before going on
        else:
            GETDATA         = partial(get_waveforms4mp, outdir=outdir, client=client, pre_filt = (0.001, 0.005, 1, 100.0), verbose=verbose, rotation=False)
            pool            = multiprocessing.Pool(processes=nprocess)
            pool.map(GETDATA, reqwaveLst) #make our results with a map call
            pool.close() #we are not adding any more processes
            pool.join() #tell it to wait until all threads are done before going on
        print('============================= End of multiprocessing download surface wave data ==============================')
        print('==================================== Reading downloaded surface wave data ====================================')
        evnumb              = 0
        no_resp             = 0
        for event in self.cat:
            event_id        = event.resource_id.id.split('=')[-1]
            magnitude       = event.magnitudes[0].mag
            Mtype           = event.magnitudes[0].magnitude_type
            event_descrip   = event.event_descriptions[0].text+', '+event.event_descriptions[0].type
            evnumb          += 1
            evid            = 'E%05d' %evnumb
            tag             = 'surf_ev_%05d' %evnumb
            otime           = event.origins[0].time
            if otime < stime4down or otime > etime4down:
                continue
            print 'Event ' + str(evnumb)+' : '+event_descrip+', '+Mtype+' = '+str(magnitude)
            for staid in self.waveforms.list():
                netcode, stacode    = staid.split('.')
                infname             = outdir+'/'+evid+'.'+staid+'.mseed'
                if os.path.isfile(infname):
                    self.add_waveforms(infname, event_id=event_id, tag=tag)
                    if deletemseed:
                        os.remove(infname)
                elif os.path.isfile(outdir+'/'+evid+'.'+staid+'.no_resp.mseed'):
                    no_resp         += 1
        print('================================== End reading downloaded surface wave data ==================================')
        print 'Number of file without resp:', no_resp
        return
    
    def get_body_waveforms(self, minDelta=30, maxDelta=150, channel='BHE,BHN,BHZ', phase='P',
                        startoffset=-30., endoffset=60.0, verbose=True, rotation=True, startdate=None, enddate=None):
        """Get body wave data from IRIS server
        ====================================================================================================================
        ::: input parameters :::
        min/maxDelta    - minimum/maximum epicentral distance, in degree
        channel         - Channel code, e.g. 'BHZ'.
                            Last character (i.e. component) can be a wildcard (‘?’ or ‘*’) to fetch Z, N and E component.
        phase           - body wave phase to be downloaded, arrival time will be computed using taup
        start/endoffset - start and end offset for downloaded data
        vmin, vmax      - minimum/maximum velocity for surface wave window
        rotation        - rotate the seismogram to RT or not
        =====================================================================================================================
        """
        client          = Client('IRIS')
        evnumb          = 0
        try:
            stime4down  = obspy.core.utcdatetime.UTCDateTime(startdate)
        except:
            stime4down  = obspy.UTCDateTime(0)
        try:
            etime4down  = obspy.core.utcdatetime.UTCDateTime(enddate)
        except:
            etime4down  = obspy.UTCDateTime()
        print('================================== Getting body wave data =====================================')
        try:
            print self.cat
        except AttributeError:
            self.copy_catalog()
        L                   = len(self.cat)
        for event in self.cat:
            event_id        = event.resource_id.id.split('=')[-1]
            magnitude       = event.magnitudes[0].mag
            Mtype           = event.magnitudes[0].magnitude_type
            event_descrip   = event.event_descriptions[0].text+', '+event.event_descriptions[0].type
            evnumb          +=1
            otime           = event.origins[0].time
            if otime < stime4down or otime > etime4down:
                continue
            print 'Event ' + str(evnumb)+' : '+ str(otime)+' '+ event_descrip+', '+Mtype+' = '+str(magnitude) 
            evlo            = event.origins[0].longitude
            evla            = event.origins[0].latitude
            evdp            = event.origins[0].depth/1000.
            tag             = 'body_ev_%05d' %evnumb
            for staid in self.waveforms.list():
                netcode, stacode    = staid.split('.')
                stla, elev, stlo    = self.waveforms[staid].coordinates.values()
                elev                = elev/1000.
                az, baz, dist       = geodist.inv(evlo, evla, stlo, stla)
                dist                = dist/1000.
                if baz<0.:
                    baz             += 360.
                Delta               = obspy.geodetics.kilometer2degrees(dist)
                if Delta<minDelta:
                    continue
                if Delta>maxDelta:
                    continue
                arrivals            = taupmodel.get_travel_times(source_depth_in_km=evdp, distance_in_degree=Delta, phase_list=[phase])#, receiver_depth_in_km=0)
                try:
                    arr             = arrivals[0]
                    arrival_time    = arr.time
                    rayparam        = arr.ray_param_sec_degree
                except IndexError:
                    continue
                starttime           = otime+arrival_time+startoffset
                endtime             = otime+arrival_time+endoffset
                location            = self.waveforms[staid].StationXML[0].stations[0].channels[0].location_code
                try:
                    st              = client.get_waveforms(network=netcode, station=stacode, location=location, channel=channel,
                                        starttime=starttime, endtime=endtime, attach_response=True)
                except:
                    if verbose:
                        print 'No data for:', staid
                    continue
                pre_filt            = (0.04, 0.05, 20., 25.)
                st.detrend()
                st.remove_response(pre_filt=pre_filt, taper_fraction=0.1)
                if rotation:
                    st.rotate('NE->RT', back_azimuth=baz)
                if verbose:
                    print 'Getting data for:', staid
                self.add_waveforms(st, event_id=event_id, tag=tag, labels=phase)
        return
    
    def get_body_waveforms_mp(self, outdir, minDelta=30, maxDelta=150, channel='BHE,BHN,BHZ', phase='P', startoffset=-30., endoffset=60.0,
            verbose=False, subsize=1000, deletemseed=False, nprocess=6, snumb=0, enumb=None, rotation=True, startdate=None, enddate=None):
        """Get body wave data from IRIS server
        ====================================================================================================================
        ::: input parameters :::
        min/maxDelta    - minimum/maximum epicentral distance, in degree
        channel         - Channel code, e.g. 'BHZ'.
                            Last character (i.e. component) can be a wildcard (‘?’ or ‘*’) to fetch Z, N and E component.
        phase           - body wave phase to be downloaded, arrival time will be computed using taup
        start/endoffset - start and end offset for downloaded data
        vmin, vmax      - minimum/maximum velocity for surface wave window
        rotation        - rotate the seismogram to RT or not
        deletemseed     - delete output MiniSeed files
        nprocess        - number of processes
        snumb, enumb    - start/end number of processing block
        =====================================================================================================================
        """
        client              = Client('IRIS')
        evnumb              = 0
        if not os.path.isdir(outdir):
            os.makedirs(outdir)
        reqwaveLst          = []
        try:
            stime4down  = obspy.core.utcdatetime.UTCDateTime(startdate)
        except:
            stime4down  = obspy.UTCDateTime(0)
        try:
            etime4down  = obspy.core.utcdatetime.UTCDateTime(enddate)
        except:
            etime4down  = obspy.UTCDateTime()
        print('================================== Preparing download body wave data ======================================')
        swave               = snumb*subsize
        iwave               = 0
        try:
            print self.cat
        except AttributeError:
            self.copy_catalog()
        L   = len(self.cat)
        for event in self.cat:
            magnitude       = event.magnitudes[0].mag; Mtype=event.magnitudes[0].magnitude_type
            event_descrip   = event.event_descriptions[0].text+', '+event.event_descriptions[0].type
            evnumb          += 1
            otime           = event.origins[0].time
            if otime < stime4down or otime > etime4down:
                continue
            print 'Event ' + str(evnumb)+' : '+ str(otime)+' '+ event_descrip+', '+Mtype+' = '+str(magnitude) 
            evlo            = event.origins[0].longitude
            evla            = event.origins[0].latitude
            evdp            = event.origins[0].depth/1000.
            for staid in self.waveforms.list():
                iwave       += 1
                if iwave < swave:
                    continue
                netcode, stacode    = staid.split('.')
                stla, elev, stlo    = self.waveforms[staid].coordinates.values()
                elev                = elev/1000.
                az, baz, dist       = geodist.inv(evlo, evla, stlo, stla)
                dist                = dist/1000.
                if baz<0.:
                    baz             += 360.
                Delta               = obspy.geodetics.kilometer2degrees(dist)
                if Delta<minDelta:
                    continue
                if Delta>maxDelta:
                    continue
                arrivals            = taupmodel.get_travel_times(source_depth_in_km=evdp, distance_in_degree=Delta, phase_list=[phase])#, receiver_depth_in_km=0)
                try:
                    arr             = arrivals[0]
                    arrival_time    = arr.time
                    rayparam        = arr.ray_param_sec_degree
                except IndexError:
                    continue
                starttime           = otime+arrival_time+startoffset
                endtime             = otime+arrival_time+endoffset
                location            = self.waveforms[staid].StationXML[0].stations[0].channels[0].location_code
                reqwaveLst.append( requestInfo(evnumb=evnumb, network=netcode, station=stacode, location=location, channel=channel,
                            starttime=starttime, endtime=endtime, attach_response=True, baz=baz) )
        print('============================= Start multiprocessing download body wave data ===============================')
        if len(reqwaveLst) > subsize:
            Nsub            = int(len(reqwaveLst)/subsize)
            # if enumb==None: enumb=Nsub
            for isub in range(Nsub):
                # if isub < snumb: continue
                # if isub > enumb: continue
                print 'Subset:', isub+1,'in',Nsub,'sets'
                creqlst     = reqwaveLst[isub*subsize:(isub+1)*subsize]
                GETDATA     = partial(get_waveforms4mp, outdir=outdir, client=client, pre_filt = (0.04, 0.05, 20., 25.), verbose=verbose, rotation=rotation)
                pool        = multiprocessing.Pool(processes=nprocess)
                pool.map(GETDATA, creqlst) #make our results with a map call
                pool.close() #we are not adding any more processes
                pool.join() #tell it to wait until all threads are done before going on
            creqlst         = reqwaveLst[(isub+1)*subsize:]
            GETDATA         = partial(get_waveforms4mp, outdir=outdir, client=client, pre_filt = (0.04, 0.05, 20., 25.), verbose=verbose, rotation=rotation)
            pool            = multiprocessing.Pool(processes=nprocess)
            pool.map(GETDATA, creqlst) #make our results with a map call
            pool.close() #we are not adding any more processes
            pool.join() #tell it to wait until all threads are done before going on
        else:
            GETDATA         = partial(get_waveforms4mp, outdir=outdir, client=client, pre_filt = (0.04, 0.05, 20., 25.), verbose=verbose, rotation=rotation)
            pool            = multiprocessing.Pool(processes=nprocess)
            pool.map(GETDATA, reqwaveLst) #make our results with a map call
            pool.close() #we are not adding any more processes
            pool.join() #tell it to wait until all threads are done before going on
        print('============================= End of multiprocessing download body wave data ==============================')
        print('==================================== Reading downloaded body wave data ====================================')
        evnumb              = 0
        no_resp             = 0
        for event in self.cat:
            event_id        = event.resource_id.id.split('=')[-1]
            magnitude       = event.magnitudes[0].mag; Mtype=event.magnitudes[0].magnitude_type
            event_descrip   = event.event_descriptions[0].text+', '+event.event_descriptions[0].type
            evnumb          += 1
            evid            = 'E%05d' %evnumb
            tag             = 'body_ev_%05d' %evnumb
            otime           = event.origins[0].time
            if otime < stime4down or otime > etime4down:
                continue
            print 'Event ' + str(evnumb)+' : '+event_descrip+', '+Mtype+' = '+str(magnitude) 
            for staid in self.waveforms.list():
                netcode, stacode    = staid.split('.')
                infname             = outdir+'/'+evid+'.'+staid+'.mseed'
                if os.path.isfile(infname):
                    self.add_waveforms(infname, event_id=event_id, tag=tag, labels=phase)
                    if deletemseed:
                        os.remove(infname)
                elif os.path.isfile(outdir+'/'+evid+'.'+staid+'.no_resp.mseed'):
                    no_resp += 1
        print('================================== End reading downloaded body wave data ==================================')
        print 'Number of file without resp:', no_resp
        return
    
    def read_body_waveforms_DMT(self, datadir, minDelta=30, maxDelta=150, startdate=None, enddate=None, rotation=True, phase='P', verbose=True):
        """read body wave data downloaded using obspyDMT
        ====================================================================================================================
        ::: input parameters :::
        datadir         - data directory
        min/maxDelta    - minimum/maximum epicentral distance, in degree
        phase           - body wave phase 
        start/enddate   - start and end date for reading downloaded data
        rotation        - rotate the seismogram to RT or not
        =====================================================================================================================
        """
        evnumb              = 0
        try:
            print self.cat
        except AttributeError:
            self.copy_catalog()
        try:
            stime4read  = obspy.core.utcdatetime.UTCDateTime(startdate)
        except:
            stime4read  = obspy.UTCDateTime(0)
        try:
            etime4read  = obspy.core.utcdatetime.UTCDateTime(enddate)
        except:
            etime4read  = obspy.UTCDateTime()
        L               = len(self.cat)
        print('==================================== Reading downloaded body wave data ====================================')
        for event in self.cat:
            event_id        = event.resource_id.id.split('=')[-1]
            pmag            = event.preferred_magnitude()
            magnitude       = pmag.mag
            Mtype           = pmag.magnitude_type
            event_descrip   = event.event_descriptions[0].text+', '+event.event_descriptions[0].type
            evnumb          +=1
            porigin         = event.preferred_origin()
            otime           = porigin.time
            if otime < stime4read or otime > etime4read:
                continue
            print('Event ' + str(evnumb)+' : '+ str(otime)+' '+ event_descrip+', '+Mtype+' = '+str(magnitude))
            evlo            = porigin.longitude
            evla            = porigin.latitude
            evdp            = porigin.depth/1000.
            tag             = 'body_ev_%05d' %evnumb
            suddatadir      = datadir+'/'+'%d%02d%02d_%02d%02d%02d.a' \
                                %(otime.year, otime.month, otime.day, otime.hour, otime.minute, otime.second)
            Ndata           = 0
            outstr          = ''
            for staid in self.waveforms.list():
                netcode, stacode    = staid.split('.')
                infpfx              = suddatadir + '/processed/'+netcode+'.'+stacode
                fnameZ              = infpfx + '..BHZ'
                fnameE              = infpfx + '..BHE'
                fnameN              = infpfx + '..BHN'
                if not (os.path.isfile(fnameZ) and os.path.isfile(fnameE) and os.path.isfile(fnameN)):
                    fnameZ          = infpfx + '.00.BHZ'
                    fnameE          = infpfx + '.00.BHE'
                    fnameN          = infpfx + '.00.BHN'
                    if not (os.path.isfile(fnameZ) and os.path.isfile(fnameE) and os.path.isfile(fnameN)):
                        fnameZ      = infpfx + '.10.BHZ'
                        fnameE      = infpfx + '.10.BHE'
                        fnameN      = infpfx + '.10.BHN'
                        if not (os.path.isfile(fnameZ) and os.path.isfile(fnameE) and os.path.isfile(fnameN)):
                            if verbose:
                                print('No data for: '+staid)
                            continue
                if verbose:
                    print 'Reading data for:', staid
                stla, elev, stlo    = self.waveforms[staid].coordinates.values()
                elev                = elev/1000.
                az, baz, dist       = geodist.inv(evlo, evla, stlo, stla)
                dist                = dist/1000.
                if baz<0.:
                    baz             += 360.
                Delta               = obspy.geodetics.kilometer2degrees(dist)
                if Delta<minDelta:
                    continue
                if Delta>maxDelta:
                    continue
                st                  = obspy.read(fnameZ)
                st                  +=obspy.read(fnameE)
                st                  +=obspy.read(fnameN)
                if len(st) != 3:
                    continue
                if rotation:
                    try:
                        st.rotate('NE->RT', back_azimuth=baz)
                    except ValueError:
                        stime4trim  = obspy.UTCDateTime(0)
                        etime4trim  = obspy.UTCDateTime()
                        for tr in st:
                            if stime4trim < tr.stats.starttime:
                                stime4trim  = tr.stats.starttime
                            if etime4trim > tr.stats.endtime:
                                etime4trim  = tr.stats.endtime
                        st.trim(starttime=stime4trim, endtime=etime4trim)
                        st.rotate('NE->RT', back_azimuth=baz)
                self.add_waveforms(st, event_id=event_id, tag=tag, labels=phase)
                Ndata   += 1
                outstr  += staid
                outstr  += ' '
            print(str(Ndata)+' data streams are stored in ASDF')
            print('STATION CODE: '+outstr)
            print('-----------------------------------------------------------------------------------------------------------')
        print('================================== End reading downloaded body wave data ==================================')
        return
    
    def read_body_waveforms_DMT_rtz(self, datadir, minDelta=30, maxDelta=150, startdate=None, enddate=None, phase='P', verbose=True):
        """read body wave data downloaded using obspyDMT, RTZ component
        ====================================================================================================================
        ::: input parameters :::
        datadir         - data directory
        min/maxDelta    - minimum/maximum epicentral distance, in degree
        phase           - body wave phase 
        start/enddate   - start and end date for reading downloaded data
        rotation        - rotate the seismogram to RT or not
        =====================================================================================================================
        """
        evnumb              = 0
        try:
            print self.cat
        except AttributeError:
            self.copy_catalog()
        try:
            stime4read  = obspy.core.utcdatetime.UTCDateTime(startdate)
        except:
            stime4read  = obspy.UTCDateTime(0)
        try:
            etime4read  = obspy.core.utcdatetime.UTCDateTime(enddate)
        except:
            etime4read  = obspy.UTCDateTime()
        L               = len(self.cat)
        print('==================================== Reading downloaded body wave data ====================================')
        for event in self.cat:
            event_id        = event.resource_id.id.split('=')[-1]
            pmag            = event.preferred_magnitude()
            magnitude       = pmag.mag
            Mtype           = pmag.magnitude_type
            event_descrip   = event.event_descriptions[0].text+', '+event.event_descriptions[0].type
            evnumb          +=1
            porigin         = event.preferred_origin()
            otime           = porigin.time
            if otime < stime4read or otime > etime4read:
                continue
            print('Event ' + str(evnumb)+' : '+ str(otime)+' '+ event_descrip+', '+Mtype+' = '+str(magnitude))
            evlo            = porigin.longitude
            evla            = porigin.latitude
            evdp            = porigin.depth/1000.
            tag             = 'body_ev_%05d' %evnumb
            suddatadir      = datadir+'/'+'%d%02d%02d_%02d%02d%02d.a' \
                                %(otime.year, otime.month, otime.day, otime.hour, otime.minute, otime.second)
            Ndata           = 0
            outstr          = ''
            for staid in self.waveforms.list():
                netcode, stacode    = staid.split('.')
                infpfx              = suddatadir + '/processed/'+netcode+'.'+stacode
                fnameZ              = infpfx + '..BHZ'
                fnameR              = infpfx + '..BHR'
                fnameT              = infpfx + '..BHT'
                if not (os.path.isfile(fnameZ) and os.path.isfile(fnameR) and os.path.isfile(fnameT)):
                    fnameZ          = infpfx + '.00.BHZ'
                    fnameR          = infpfx + '.00.BHR'
                    fnameT          = infpfx + '.00.BHT'
                    if not (os.path.isfile(fnameZ) and os.path.isfile(fnameR) and os.path.isfile(fnameT)):
                        fnameZ      = infpfx + '.10.BHZ'
                        fnameR      = infpfx + '.10.BHR'
                        fnameT      = infpfx + '.10.BHT'
                        if not (os.path.isfile(fnameZ) and os.path.isfile(fnameR) and os.path.isfile(fnameT)):
                            if verbose:
                                print('No data for: '+staid)
                            continue
                if verbose:
                    print 'Reading data for:', staid
                stla, elev, stlo    = self.waveforms[staid].coordinates.values()
                elev                = elev/1000.
                az, baz, dist       = geodist.inv(evlo, evla, stlo, stla)
                dist                = dist/1000.
                if baz<0.:
                    baz             += 360.
                Delta               = obspy.geodetics.kilometer2degrees(dist)
                if Delta<minDelta:
                    continue
                if Delta>maxDelta:
                    continue
                st                  = obspy.read(fnameZ)
                st                  +=obspy.read(fnameR)
                st                  +=obspy.read(fnameT)
                if len(st) != 3:
                    continue
                self.add_waveforms(st, event_id=event_id, tag=tag, labels=phase)
                Ndata   += 1
                outstr  += staid
                outstr  += ' '
            print(str(Ndata)+' data streams are stored in ASDF')
            print('STATION CODE: '+outstr)
            print('-----------------------------------------------------------------------------------------------------------')
        print('================================== End reading downloaded body wave data ==================================')
        return
    
    

    def write2sac(self, network, station, evnumb, datatype='body'):
        """ Extract data from ASDF to SAC file
        ====================================================================================================================
        input parameters:
        network, station    - specify station
        evnumb              - event id
        datatype            - data type ('body' - body wave, 'surf' - surface wave)
        =====================================================================================================================
        """
        event           = self.events[evnumb-1]
        otime           = event.origins[0].time
        tag             = datatype+'_ev_%05d' %evnumb
        st              = self.waveforms[network+'.'+station][tag]
        stla, elev, stlo= self.waveforms[network+'.'+station].coordinates.values()
        evlo            = event.origins[0].longitude
        evla            = event.origins[0].latitude
        evdp            = event.origins[0].depth
        for tr in st:
            tr.stats.sac            = obspy.core.util.attribdict.AttribDict()
            tr.stats.sac['evlo']    = evlo
            tr.stats.sac['evla']    = evla
            tr.stats.sac['evdp']    = evdp
            tr.stats.sac['stlo']    = stlo
            tr.stats.sac['stla']    = stla    
        st.write(str(otime)+'..sac', format='sac')
        return
    
    def get_obspy_trace(self, network, station, evnumb, datatype='body'):
        """ Get obspy trace data from ASDF
        ====================================================================================================================
        input parameters:
        network, station    - specify station
        evnumb              - event id
        datatype            - data type ('body' - body wave, 'surf' - surface wave)
        =====================================================================================================================
        """
        event               = self.events[evnumb-1]
        tag                 = datatype+'_ev_%05d' %evnumb
        st                  = self.waveforms[network+'.'+station][tag]
        stla, elev, stlo    = self.waveforms[network+'.'+station].coordinates.values()
        evlo                = event.origins[0].longitude
        evla                = event.origins[0].latitude
        evdp                = event.origins[0].depth
        for tr in st:
            tr.stats.sac            = obspy.core.util.attribdict.AttribDict()
            tr.stats.sac['evlo']    = evlo
            tr.stats.sac['evla']    = evla
            tr.stats.sac['evdp']    = evdp
            tr.stats.sac['stlo']    = stlo
            tr.stats.sac['stla']    = stla    
        return st
    
    def compute_ref(self, inrefparam=CURefPy.InputRefparam(), savescaled=True, savemoveout=True, verbose=True, startdate=None, enddate=None):
        """Compute receiver function and post processed data(moveout, stretchback)
        ====================================================================================================================
        ::: input parameters :::
        inrefparam      - input parameters for receiver function, refer to InputRefparam in CURefPy for details
        savescaled      - save scaled post processed data
        savemoveout     - save moveout data
        =====================================================================================================================
        """
        try:
            print self.cat
        except AttributeError:
            self.copy_catalog()
        try:
            stime4ref   = obspy.core.utcdatetime.UTCDateTime(startdate)
        except:
            stime4ref   = obspy.UTCDateTime(0)
        try:
            etime4ref   = obspy.core.utcdatetime.UTCDateTime(enddate)
        except:
            etime4ref   = obspy.UTCDateTime()
        print '================================== Receiver Function Analysis ======================================'
        for staid in self.waveforms.list():
            netcode, stacode    = staid.split('.')
            print('Station: '+staid)
            stla, elev, stlo    = self.waveforms[staid].coordinates.values()
            evnumb              = 0
            # Ndata               
            for event in self.cat:
                evnumb          += 1
                evid            = 'E%05d' %evnumb
                tag             = 'body_ev_%05d' %evnumb
                try:
                    st          = self.waveforms[staid][tag]
                except KeyError:
                    continue
                if len(st) != 3:
                    continue
                phase           = st[0].stats.asdf.labels[0]
                if inrefparam.phase != '' and inrefparam.phase != phase:
                    continue
                porigin         = event.preferred_origin()
                evlo            = porigin.longitude
                evla            = porigin.latitude
                evdp            = porigin.depth
                otime           = porigin.time
                if otime < stime4ref or otime > etime4ref:
                    continue
                for tr in st:
                    tr.stats.sac        = obspy.core.util.attribdict.AttribDict()
                    tr.stats.sac['evlo']= evlo
                    tr.stats.sac['evla']= evla
                    tr.stats.sac['evdp']= evdp
                    tr.stats.sac['stlo']= stlo
                    tr.stats.sac['stla']= stla
                if verbose:
                    pmag            = event.preferred_magnitude()
                    magnitude       = pmag.mag
                    Mtype           = pmag.magnitude_type
                    event_descrip   = event.event_descriptions[0].text+', '+event.event_descriptions[0].type
                    print('Event ' + str(evnumb)+' : '+event_descrip+', '+Mtype+' = '+str(magnitude))
                refTr               = CURefPy.RFTrace()
                refTr.get_data(Ztr=st.select(component='Z')[0], RTtr=st.select(component=inrefparam.reftype)[0],
                        tbeg=inrefparam.tbeg, tend=inrefparam.tend)
                refTr.IterDeconv( tdel=inrefparam.tdel, f0 = inrefparam.f0, niter=inrefparam.niter,
                        minderr=inrefparam.minderr, phase=phase )
                ref_header              = ref_header_default.copy()
                ref_header['otime']     = str(otime)
                ref_header['network']   = netcode
                ref_header['station']   = stacode
                ref_header['stla']      = stla
                ref_header['stlo']      = stlo
                ref_header['evla']      = evla
                ref_header['evlo']      = evlo
                ref_header['evdp']      = evdp
                ref_header['dist']      = refTr.stats.sac['dist']
                ref_header['az']        = refTr.stats.sac['az']
                ref_header['baz']       = refTr.stats.sac['baz']
                ref_header['delta']     = refTr.stats.delta
                ref_header['npts']      = refTr.stats.npts
                ref_header['b']         = refTr.stats.sac['b']
                ref_header['e']         = refTr.stats.sac['e']
                ref_header['arrival']   = refTr.stats.sac['user5']
                ref_header['phase']     = phase
                ref_header['tbeg']      = inrefparam.tbeg
                ref_header['tend']      = inrefparam.tend
                ref_header['hslowness'] = refTr.stats.sac['user4']
                ref_header['ghw']       = inrefparam.f0
                ref_header['VR']        = refTr.stats.sac['user2']
                staid_aux               = netcode+'_'+stacode+'_'+phase+'/'+evid
                self.add_auxiliary_data(data=refTr.data, data_type='Ref'+inrefparam.reftype, path=staid_aux, parameters=ref_header)
                # move out to vertically incident receiver function
                if not refTr.move_out():
                    continue
                # stretch back to reference slowness
                refTr.stretch_back()
                postdbase               = refTr.postdbase
                ref_header['moveout']   = postdbase.MoveOutFlag
                if savescaled:
                    self.add_auxiliary_data(data=postdbase.ampC, data_type='Ref'+inrefparam.reftype+'scaled', path=staid_aux, parameters=ref_header)
                if savemoveout:
                    self.add_auxiliary_data(data=postdbase.ampTC, data_type='Ref'+inrefparam.reftype+'moveout', path=staid_aux, parameters=ref_header)
                self.add_auxiliary_data(data=postdbase.strback, data_type='Ref'+inrefparam.reftype+'streback', path=staid_aux, parameters=ref_header)
        return
    
    def compute_ref_mp(self, outdir, inrefparam=CURefPy.InputRefparam(), savescaled=True, savemoveout=True, \
                verbose=False, subsize=1000, deleteref=True, deletepost=True, nprocess=None, startdate=None, enddate=None):
        """Compute receiver function and post processed data(moveout, stretchback) with multiprocessing
        ====================================================================================================================
        ::: input parameters :::
        inrefparam      - input parameters for receiver function, refer to InputRefparam in CURefPy for details
        savescaled      - save scaled post processed data
        savemoveout     - save moveout data
        subsize         - subsize of processing list, use to prevent lock in multiprocessing process
        deleteref       - delete SAC receiver function data
        deletepost      - delete npz post processed data
        nprocess        - number of processes
        =====================================================================================================================
        """
        print('================================== Receiver Function Analysis ======================================')
        print('Preparing data for multiprocessing')
        try:
            print self.cat
        except AttributeError:
            self.copy_catalog()
        try:
            stime4ref       = obspy.core.utcdatetime.UTCDateTime(startdate)
        except:
            stime4ref       = obspy.UTCDateTime(0)
        try:
            etime4ref       = obspy.core.utcdatetime.UTCDateTime(enddate)
        except: 
            etime4ref       = obspy.UTCDateTime()
        refLst              = []
        for staid in self.waveforms.list():
            netcode, stacode= staid.split('.')
            print('Station: '+staid)
            stla, elev, stlo= self.waveforms[staid].coordinates.values()
            evnumb          = 0
            outsta          = outdir+'/'+staid
            if not os.path.isdir(outsta):
                os.makedirs(outsta)
            for event in self.cat:
                evnumb      +=1
                evid        = 'E%05d' %evnumb
                tag         = 'body_ev_%05d' %evnumb
                try:
                    st      = self.waveforms[staid][tag]
                except KeyError:
                    continue
                phase       = st[0].stats.asdf.labels[0]
                if inrefparam.phase != '' and inrefparam.phase != phase:
                    continue
                porigin         = event.preferred_origin()
                evlo            = porigin.longitude
                evla            = porigin.latitude
                evdp            = porigin.depth
                otime           = porigin.time
                if otime < stime4ref or otime > etime4ref:
                    continue
                for tr in st:
                    tr.stats.sac            = obspy.core.util.attribdict.AttribDict()
                    tr.stats.sac['evlo']    = evlo
                    tr.stats.sac['evla']    = evla
                    tr.stats.sac['evdp']    = evdp
                    tr.stats.sac['stlo']    = stlo
                    tr.stats.sac['stla']    = stla
                    tr.stats.sac['kuser0']  = evid
                    tr.stats.sac['kuser1']  = phase
                if verbose:
                    pmag            = event.preferred_magnitude()
                    magnitude       = pmag.mag
                    Mtype           = pmag.magnitude_type
                    event_descrip   = event.event_descriptions[0].text+', '+event.event_descriptions[0].type
                    print('Event ' + str(evnumb)+' : '+event_descrip+', '+Mtype+' = '+str(magnitude))
                refTr               = CURefPy.RFTrace()
                refTr.get_data(Ztr=st.select(component='Z')[0], RTtr=st.select(component=inrefparam.reftype)[0],
                        tbeg=inrefparam.tbeg, tend=inrefparam.tend)
                refLst.append( refTr )
        print('Start multiprocessing receiver function analysis !')
        if len(refLst) > subsize:
            Nsub            = int(len(refLst)/subsize)
            for isub in range(Nsub):
                print 'Subset:', isub,'in',Nsub,'sets'
                cstream     = refLst[isub*subsize:(isub+1)*subsize]
                REF         = partial(ref4mp, outdir=outsta, inrefparam=inrefparam)
                pool        = multiprocessing.Pool(processes=nprocess)
                pool.map(REF, cstream) #make our results with a map call
                pool.close() #we are not adding any more processes
                pool.join() #tell it to wait until all threads are done before going on
            cstream         = refLst[(isub+1)*subsize:]
            REF             = partial(ref4mp, outdir=outsta, inrefparam=inrefparam)
            pool            = multiprocessing.Pool(processes=nprocess)
            pool.map(REF, cstream) #make our results with a map call
            pool.close() #we are not adding any more processes
            pool.join() #tell it to wait until all threads are done before going on
        else:
            REF             = partial(ref4mp, outdir=outsta, inrefparam=inrefparam)
            pool            = multiprocessing.Pool(processes=nprocess)
            pool.map(REF, refLst) #make our results with a map call
            pool.close() #we are not adding any more processes
            pool.join() #tell it to wait until all threads are done before going on
        print('End of multiprocessing receiver function analysis !')
        print('Start reading receiver function data !')
        for staid in self.waveforms.list():
            netcode, stacode    = staid.split('.')
            print('Station: '+staid)
            stla, elev, stlo    = self.waveforms[staid].coordinates.values()
            outsta              = outdir+'/'+staid
            evnumb              = 0
            for event in self.cat:
                evnumb          +=1
                evid            ='E%05d' %evnumb
                sacfname        = outsta+'/'+evid+'.sac'; postfname = outsta+'/'+evid+'.post.npz'
                if not os.path.isfile(sacfname):
                    continue
                evlo                    = event.origins[0].longitude
                evla                    = event.origins[0].latitude
                evdp                    = event.origins[0].depth
                otime                   = event.origins[0].time
                refTr                   = obspy.read(sacfname)[0]
                ref_header              = ref_header_default.copy()
                ref_header['otime']     = str(otime)
                ref_header['network']   = netcode
                ref_header['station']   = stacode
                ref_header['stla']      = stla
                ref_header['stlo']      = stlo
                ref_header['evla']      = evla
                ref_header['evlo']      = evlo
                ref_header['evdp']      = evdp
                ref_header['dist']      = refTr.stats.sac['dist']
                ref_header['az']        = refTr.stats.sac['az']
                ref_header['baz']       = refTr.stats.sac['baz']
                ref_header['delta']     = refTr.stats.delta
                ref_header['npts']      = refTr.stats.npts
                ref_header['b']         = refTr.stats.sac['b']
                ref_header['e']         = refTr.stats.sac['e']
                ref_header['arrival']   = refTr.stats.sac['user5']
                ref_header['phase']     = refTr.stats.sac['kuser1']
                ref_header['tbeg']      = inrefparam.tbeg
                ref_header['tend']      = inrefparam.tend
                ref_header['hslowness'] = refTr.stats.sac['user4']
                ref_header['ghw']       = inrefparam.f0
                ref_header['VR']        = refTr.stats.sac['user2']
                staid_aux               = netcode+'_'+stacode+'_'+phase+'/'+evid
                self.add_auxiliary_data(data=refTr.data, data_type='Ref'+inrefparam.reftype, path=staid_aux, parameters=ref_header)
                if deleteref:
                    os.remove(sacfname)
                if not os.path.isfile(postfname):
                    continue
                ref_header['moveout']   = 1
                postArr                 = np.load(postfname)
                ampC                    = postArr['arr_0']
                ampTC                   = postArr['arr_1']
                strback                 = postArr['arr_2']
                if deletepost:
                    os.remove(postfname)
                if savescaled:
                    self.add_auxiliary_data(data=ampC, data_type='Ref'+inrefparam.reftype+'scaled', path=staid_aux, parameters=ref_header)
                if savemoveout:
                    self.add_auxiliary_data(data=ampTC, data_type='Ref'+inrefparam.reftype+'moveout', path=staid_aux, parameters=ref_header)
                self.add_auxiliary_data(data=strback, data_type='Ref'+inrefparam.reftype+'streback', path=staid_aux, parameters=ref_header)
            if deleteref*deletepost:
                shutil.rmtree(outsta)
        print('End reading receiver function data !')       
        return
    
    def harmonic_stripping(self, outdir, data_type='RefRstreback', VR=80, tdiff=0.08, phase='P', reftype='R'):
        """Harmonic stripping analysis
        ====================================================================================================================
        ::: input parameters :::
        outdir          - output directory
        data_type       - datatype, default is 'RefRstreback', stretchback radial receiver function
        VR              - threshold variance reduction for quality control
        tdiff           - threshold trace difference for quality control
        phase           - phase, default = 'P'
        reftype         - receiver function type, default = 'R'
        =====================================================================================================================
        """
        print '================================== Harmonic Stripping Analysis ======================================'
        for staid in self.waveforms.list():
            netcode, stacode    = staid.split('.')
            print('Station: '+staid)
            stla, elev, stlo    = self.waveforms[staid].coordinates.values()
            evnumb              = 0
            postLst             = CURefPy.PostRefLst()
            outsta              = outdir+'/'+staid
            if not os.path.isdir(outsta):
                os.makedirs(outsta)
            for event in self.events:
                evnumb          +=1
                evid            = 'E%05d' %evnumb
                try:
                    subdset     = self.auxiliary_data[data_type][netcode+'_'+stacode+'_'+phase][evid]
                except KeyError:
                    continue
                ref_header      = subdset.parameters
                if ref_header['moveout'] <0 or ref_header['VR'] < VR:
                    continue
                pdbase          = CURefPy.PostDatabase()
                pdbase.strback  = subdset.data.value; pdbase.header=subdset.parameters
                postLst.append(pdbase)
            qcLst               = postLst.remove_bad(outsta)
            qcLst               = qcLst.QControl_tdiff(tdiff=tdiff)
            qcLst.HarmonicStripping(outdir=outsta, stacode=staid)
            staid_aux           = netcode+'_'+stacode+'_'+phase
            # wmean.txt
            wmeanArr            = np.loadtxt(outsta+'/wmean.txt'); os.remove(outsta+'/wmean.txt')
            self.add_auxiliary_data(data=wmeanArr, data_type='Ref'+reftype+'HS',
                    path=staid_aux+'/wmean', parameters={})
            # bin_%d_txt
            for binfname in glob.glob(outsta+'/bin_*_txt'):
                binArr          = np.loadtxt(binfname); os.remove(binfname)
                temp            = binfname.split('/')[-1]
                self.add_auxiliary_data(data=binArr, data_type='Ref'+reftype+'HS',
                        path=staid_aux+'/bin/'+temp.split('_')[0]+'_'+temp.split('_')[1], parameters={})
            for binfname in glob.glob(outsta+'/bin_*_rf.dat'):
                binArr          = np.loadtxt(binfname); os.remove(binfname)
                temp            = binfname.split('/')[-1]
                self.add_auxiliary_data(data=binArr, data_type='Ref'+reftype+'HS',
                        path=staid_aux+'/bin_rf/'+temp.split('_')[0]+'_'+temp.split('_')[1], parameters={})
            # A0.dat
            A0Arr               = np.loadtxt(outsta+'/A0.dat')
            os.remove(outsta+'/A0.dat')
            self.add_auxiliary_data(data=A0Arr, data_type='Ref'+reftype+'HS',
                    path=staid_aux+'/A0', parameters={})
            # A1.dat
            A1Arr               = np.loadtxt(outsta+'/A1.dat')
            os.remove(outsta+'/A1.dat')
            self.add_auxiliary_data(data=A1Arr, data_type='Ref'+reftype+'HS',
                    path=staid_aux+'/A1', parameters={})
            # A2.dat
            A2Arr               = np.loadtxt(outsta+'/A2.dat')
            os.remove(outsta+'/A2.dat')
            self.add_auxiliary_data(data=A2Arr, data_type='Ref'+reftype+'HS',
                    path=staid_aux+'/A2', parameters={})
            # A0_A1_A2.dat
            A0A1A2Arr           = np.loadtxt(outsta+'/A0_A1_A2.dat')
            os.remove(outsta+'/A0_A1_A2.dat')
            self.add_auxiliary_data(data=A0A1A2Arr, data_type='Ref'+reftype+'HS',
                    path=staid_aux+'/A0_A1_A2', parameters={})
            evnumb              = 0
            for event in self.events:
                evnumb          +=1
                evid            = 'E%05d' %evnumb
                try:
                    subdset     = self.auxiliary_data[data_type][netcode+'_'+stacode+'_'+phase][evid]
                except KeyError:
                    continue
                ref_header      = subdset.parameters
                if ref_header['moveout'] <0 or ref_header['VR'] < VR:
                    continue
                otime           = ref_header['otime']; baz=ref_header['baz']
                fsfx            = str(int(baz))+'_'+staid+'_'+otime+'.out.back'
                diff_fname      = outsta+'/diffstre_'+fsfx
                obsfname        = outsta+'/obsstre_'+fsfx
                repfname        = outsta+'/repstre_'+fsfx
                rep0fname       = outsta+'/0repstre_'+fsfx
                rep1fname       = outsta+'/1repstre_'+fsfx
                rep2fname       = outsta+'/2repstre_'+fsfx
                prefname        = outsta+'/prestre_'+fsfx
                if not (os.path.isfile(diff_fname) and os.path.isfile(obsfname) and os.path.isfile(repfname) and \
                        os.path.isfile(rep0fname) and os.path.isfile(rep1fname) and os.path.isfile(rep2fname) and os.path.isfile(prefname) ):
                    continue
                diffArr         = np.loadtxt(diff_fname);   os.remove(diff_fname)
                obsArr          = np.loadtxt(obsfname);     os.remove(obsfname)
                repArr          = np.loadtxt(repfname);     os.remove(repfname)
                rep0Arr         = np.loadtxt(rep0fname);    os.remove(rep0fname)
                rep1Arr         = np.loadtxt(rep1fname);    os.remove(rep1fname)
                rep2Arr         = np.loadtxt(rep2fname);    os.remove(rep2fname)
                preArr          = np.loadtxt(prefname);     os.remove(prefname)
                self.add_auxiliary_data(data=obsArr, data_type='Ref'+reftype+'HS',
                    path=staid_aux+'/obs/'+evid, parameters=ref_header)
                self.add_auxiliary_data(data=diffArr, data_type='Ref'+reftype+'HS',
                    path=staid_aux+'/diff/'+evid, parameters=ref_header)
                self.add_auxiliary_data(data=repArr, data_type='Ref'+reftype+'HS',
                    path=staid_aux+'/rep/'+evid, parameters=ref_header)
                self.add_auxiliary_data(data=rep0Arr, data_type='Ref'+reftype+'HS',
                    path=staid_aux+'/rep0/'+evid, parameters=ref_header)
                self.add_auxiliary_data(data=rep1Arr, data_type='Ref'+reftype+'HS',
                    path=staid_aux+'/rep1/'+evid, parameters=ref_header)
                self.add_auxiliary_data(data=rep2Arr, data_type='Ref'+reftype+'HS',
                    path=staid_aux+'/rep2/'+evid, parameters=ref_header)
                self.add_auxiliary_data(data=preArr, data_type='Ref'+reftype+'HS',
                    path=staid_aux+'/pre/'+evid, parameters=ref_header)
        return
    
    def plot_ref(self, network, station, phase='P', datatype='RefRHS'):
        """plot receiver function
        ====================================================================================================================
        ::: input parameters :::
        network, station    - specify station
        phase               - phase, default = 'P'
        datatype            - datatype, default = 'RefRHS', harmonic striped radial receiver function
        =====================================================================================================================
        """
        obsHSstream = CURefPy.HStripStream()
        diffHSstream= CURefPy.HStripStream()
        repHSstream = CURefPy.HStripStream()
        rep0HSstream= CURefPy.HStripStream()
        rep1HSstream= CURefPy.HStripStream()
        rep2HSstream= CURefPy.HStripStream()
        subgroup=self.auxiliary_data[datatype][network+'_'+station+'_'+phase]
        stla, elev, stlo=self.waveforms[network+'.'+station].coordinates.values()
        for evid in subgroup.obs.list():
            ref_header=subgroup['obs'][evid].parameters
            dt=ref_header['delta']; baz=ref_header['baz']; eventT=ref_header['otime']
            obsArr=subgroup['obs'][evid].data.value
            starttime=obspy.core.utcdatetime.UTCDateTime(eventT)+ref_header['arrival']-ref_header['tbeg']+30.
            obsHSstream.get_trace(network=network, station=station, indata=obsArr[:, 1], baz=baz, dt=dt, starttime=starttime)
            
            diffArr=subgroup['diff'][evid].data.value
            diffHSstream.get_trace(network=network, station=station, indata=diffArr[:, 1], baz=baz, dt=dt, starttime=starttime)
            
            repArr=subgroup['rep'][evid].data.value
            repHSstream.get_trace(network=network, station=station, indata=repArr[:, 1], baz=baz, dt=dt, starttime=starttime)
            
            rep0Arr=subgroup['rep0'][evid].data.value
            rep0HSstream.get_trace(network=network, station=station, indata=rep0Arr[:, 1], baz=baz, dt=dt, starttime=starttime)
            
            rep1Arr=subgroup['rep1'][evid].data.value
            rep1HSstream.get_trace(network=network, station=station, indata=rep1Arr[:, 1], baz=baz, dt=dt, starttime=starttime)
            
            rep2Arr=subgroup['rep2'][evid].data.value
            rep2HSstream.get_trace(network=network, station=station, indata=rep2Arr[:, 1], baz=baz, dt=dt, starttime=starttime)
        self.HSDataBase=CURefPy.HarmonicStrippingDataBase(obsST=obsHSstream, diffST=diffHSstream, repST=repHSstream,\
            repST0=rep0HSstream, repST1=rep1HSstream, repST2=rep2HSstream)
        self.HSDataBase.PlotHSStreams(stacode=network+'.'+station, longitude=stlo, latitude=stla)
        return

    def array_processing(self, evnumb=1, win_len=20., win_frac=0.2, sll_x=-3.0, slm_x=3.0, sll_y=-3.0, slm_y=3.0, sl_s=0.03,
            frqlow=0.0125, frqhigh=0.02, semb_thres=-1e9, vel_thres=-1e9, prewhiten=0, verbose=True, coordsys='lonlat', timestamp='mlabday',
                method=0, minlat=None, maxlat=None, minlon=None, maxlon=None, lon0=None, lat0=None, radius=None, Tmin=None, Tmax=None, vmax=5.0, vmin=2.0):
        """Array processing ( beamforming/fk analysis )
        ==============================================================================================================================================
        ::: input parameters :::
        evnumb          - event number for analysis
        win_len         - Sliding window length in seconds
        win_frac        - Fraction of sliding window to use for step
        sll_x, slm_x    - slowness x min/max
        sll_y, slm_y    - slowness y min/max 
        sl_s            - slowness step
        semb_thres      - Threshold for semblance
        vel_thres       - Threshold for velocity
        frqlow, frqhigh - lower/higher frequency for fk/capon
        prewhiten       - Do prewhitening, values: 1 or 0
        coordsys        - valid values: ‘lonlat’ and ‘xy’, choose which stream attributes to use for coordinates
        timestamp       - valid values: ‘julsec’ and ‘mlabday’; ‘julsec’ returns the timestamp in seconds since 1970-01-01T00:00:00,
                            ‘mlabday’ returns the timestamp in days (decimals represent hours, minutes and seconds) since ‘0001-01-01T00:00:00’
                                as needed for matplotlib date plotting (see e.g. matplotlib’s num2date)
        method          - the method to use 0 == bf, 1 == capon
        minlat, maxlat  - latitude limit for stations
        minlon, maxlon  - longitude limit for stations
        lon0, lat0      - origin for radius selection
        radius          - radius for station selection
        Tmin, Tmax      - minimum/maximum time
        vmin, vmax      - minimum/maximum velocity for surface wave window, will not be used if Tmin or Tmax is specified
        ==============================================================================================================================================
        """
        # prepare Stream data
        tag='surf_ev_%05d' %evnumb
        st=obspy.Stream()
        lons=np.array([]); lats=np.array([])
        for staid in self.waveforms.list():
            stla, elev, stlo=self.waveforms[staid].coordinates.values()
            if minlat!=None:
                if stla<minlat: continue
            if maxlat!=None:
                if stla>maxlat: continue
            if minlon!=None:
                if stlo<minlon: continue
            if maxlon!=None:
                if stlo>maxlon: continue
            if lon0 !=None and lat0!=None and radius !=None:
                dist, az, baz=obspy.geodetics.gps2dist_azimuth(lat0, lon0, stla, stlo) # distance is in m
                if dist/1000>radius: continue
            try:
                tr = self.waveforms[staid][tag][0].copy()
                tr.stats.coordinates = obspy.core.util.attribdict.AttribDict({
                    'latitude': stla,
                    'elevation': elev,
                    'longitude': stlo})
                st.append(tr)
                lons=np.append(lons, stlo)
                lats=np.append(lats, stla)
            except KeyError:
                print 'no data:', staid
        if len(st)==0: print 'No data for array processing!'; return
        event = self.events[0]
        evlo=event.origins[0].longitude; evla=event.origins[0].latitude
        if lon0 !=None and lat0!=None:
            dist0, az, baz=obspy.geodetics.gps2dist_azimuth(lat0, lon0, evla, evlo) # distance is in m
        else:
            try: meanlat=(minlat+maxlat)/2; meanlon=(minlon+maxlon)/2; dist0, az, baz=obspy.geodetics.gps2dist_azimuth(lat0, lon0, meanlat, meanlon)
            except: dist0, az, baz=obspy.geodetics.gps2dist_azimuth(lat0, lon0, lats.mean(), lons.mean())
        dist0=dist0/1000.
        otime=event.origins[0].time
        if Tmin==None: stime=otime+dist0/vmax
        else: stime=otime+Tmin
        if Tmax==None: etime=otime+dist0/vmin
        else: etime=otime+Tmax
        # set input
        kwargs = dict(
            # slowness grid: X min, X max, Y min, Y max, Slow Step
            sll_x=sll_x, slm_x=slm_x, sll_y=sll_y, slm_y=slm_y, sl_s=sl_s,
            # sliding window properties
            win_len=win_len, win_frac=win_frac,
            # frequency properties
            frqlow=frqlow, frqhigh=frqhigh, prewhiten=0,
            # restrict output
            semb_thres=semb_thres, vel_thres=vel_thres, timestamp=timestamp,
            stime=stime, etime=etime, method=method,
            verbose=verbose
        )
        # array analysis
        out = obspy.signal.array_analysis.array_processing(st, **kwargs)
        # Plot
        labels = ['rel.power', 'abs.power', 'baz', 'slow']
        xlocator = mdates.AutoDateLocator()
        fig = plt.figure()
        for i, lab in enumerate(labels):
            ax = fig.add_subplot(4, 1, i + 1)
            ax.scatter(out[:, 0], out[:, i + 1], c=out[:, 1], alpha=0.6,
                       edgecolors='none', cmap=obspy_sequential)
            ax.set_ylabel(lab)
            ax.set_xlim(out[0, 0], out[-1, 0])
            ax.set_ylim(out[:, i + 1].min(), out[:, i + 1].max())
            ax.xaxis.set_major_locator(xlocator)
            ax.xaxis.set_major_formatter(mdates.AutoDateFormatter(xlocator))
        
        fig.suptitle('Array analysis %s' % (
            stime.strftime('%Y-%m-%d'), ))
        fig.autofmt_xdate()
        fig.subplots_adjust(left=0.15, top=0.95, right=0.95, bottom=0.2, hspace=0)
        plt.show()
        return 
    
    def quake_prephp(self, outdir, mapfile='./MAPS/smpkolya_phv'):
        """
        Generate predicted phase velocity dispersion curves for event-station pairs
        ====================================================================================
        ::: input parameters :::
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
        evnumb=0
        for event in self.events:
            evnumb+=1
            evlo=event.origins[0].longitude; evla=event.origins[0].latitude
            evid='E%05d' % evnumb
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
                    stla, stz, stlo=self.waveforms[station_id].coordinates.values()
                    if ( abs(stlo-evlo) < 0.1 and abs(stla-evla)<0.1 ): continue
                    ista=ista+1
                    f.writelines('%5d%5d %15s %15s %10.5f %10.5f %10.5f %10.5f \n'
                            %(1, ista, evid, station_id, evla, evlo, stla, stlo ))
            call([prephaseEXE, pathfname, mapfile, perlst, evid])
            os.remove(pathfname)
            outdirL=outdir+'_L'
            outdirR=outdir+'_R'
            if not os.path.isdir(outdirL): os.makedirs(outdirL)
            if not os.path.isdir(outdirR): os.makedirs(outdirR)
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
    
    def quake_aftan(self, channel='Z', tb=0., outdir=None, inftan=pyaftan.InputFtanParam(), basic1=True, basic2=True, \
            pmf1=True, pmf2=True, verbose=True, prephdir=None, f77=True, pfx='DISP'):
        """ aftan analysis of earthquake data 
        =======================================================================================
        ::: input parameters :::
        channel     - channel pair for aftan analysis('Z', 'R', 'T')
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
        evnumb=0
        for event in self.events:
            evnumb+=1
            evlo=event.origins[0].longitude; evla=event.origins[0].latitude
            otime=event.origins[0].time
            tag='surf_ev_%05d' %evnumb
            evid='E%05d' % evnumb
            for staid in staLst:
                netcode, stacode=staid.split('.')
                stla, stz, stlo=self.waveforms[staid].coordinates.values()
                az, baz, dist = geodist.inv(evlo, evla, stlo, stla); dist=dist/1000. 
                if baz<0: baz+=360.
                try:
                    if channel!='R' or channel!='T':
                        inST=self.waveforms[staid][tag].select(component=channel)
                    else:
                        st=self.waveforms[staid][tag]
                        st.rotate('NE->RT', backazimuth=baz) 
                        inST=st.select(component=channel)
                except KeyError: continue
                if len(inST)==0: continue
                else: tr=inST[0]
                stime=tr.stats.starttime; etime=tr.stats.endtime
                tr.stats.sac={}; tr.stats.sac['dist']= dist; tr.stats.sac['b']=stime-otime; tr.stats.sac['e']=etime-otime
                aftanTr=pyaftan.aftantrace(tr.data, tr.stats)
                if prephdir !=None: phvelname = prephdir + "/%s.%s.pre" %(evid, staid)
                else: phvelname =''
                if f77:
                    aftanTr.aftanf77(pmf=inftan.pmf, piover4=inftan.piover4, vmin=inftan.vmin, vmax=inftan.vmax, tmin=inftan.tmin, tmax=inftan.tmax,
                        tresh=inftan.tresh, ffact=inftan.ffact, taperl=inftan.taperl, snr=inftan.snr, fmatch=inftan.fmatch, nfin=inftan.nfin,
                            npoints=inftan.npoints, perc=inftan.perc, phvelname=phvelname)
                else:
                    aftanTr.aftan(pmf=inftan.pmf, piover4=inftan.piover4, vmin=inftan.vmin, vmax=inftan.vmax, tmin=inftan.tmin, tmax=inftan.tmax,
                        tresh=inftan.tresh, ffact=inftan.ffact, taperl=inftan.taperl, snr=inftan.snr, fmatch=inftan.fmatch, nfin=inftan.nfin,
                            npoints=inftan.npoints, perc=inftan.perc, phvelname=phvelname)
                if verbose: print 'aftan analysis for: ' + evid+' '+staid+'_'+channel
                aftanTr.get_snr(ffact=inftan.ffact) # SNR analysis
                staid_aux=evid+'/'+netcode+'_'+stacode+'_'+channel
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
                    if not os.path.isdir(outdir+'/'+pfx+'/'+evid):
                        os.makedirs(outdir+'/'+pfx+'/'+evid)
                    foutPR=outdir+'/'+pfx+'/'+evid+'/'+ staid+'_'+channel+'.SAC'
                    aftanTr.ftanparam.writeDISP(foutPR)
        print 'End aftan analysis!'
        return
               
    def quake_aftan_mp(self, outdir, channel='Z', tb=0., inftan=pyaftan.InputFtanParam(), basic1=True, basic2=True,
            pmf1=True, pmf2=True, verbose=True, prephdir=None, f77=True, pfx='DISP', subsize=1000, deletedisp=True, nprocess=None):
        """ aftan analysis of earthquake data with multiprocessing
        =======================================================================================
        ::: input parameters :::
        channel     - channel pair for aftan analysis('Z', 'R', 'T')
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
        evnumb=0
        for event in self.events:
            evnumb+=1
            evlo=event.origins[0].longitude; evla=event.origins[0].latitude
            otime=event.origins[0].time
            tag='surf_ev_%05d' %evnumb
            evid='E%05d' % evnumb
            if not os.path.isdir(outdir+'/'+pfx+'/'+evid): os.makedirs(outdir+'/'+pfx+'/'+evid)
            for staid in staLst:
                netcode, stacode=staid.split('.')
                stla, stz, stlo=self.waveforms[staid].coordinates.values()
                # event should be initial point, station is end point, then we use baz to to rotation!
                az, baz, dist = geodist.inv(evlo, evla, stlo, stla); dist=dist/1000. 
                if baz<0: baz+=360.
                try:
                    if channel!='R' or channel!='T':
                        inST=self.waveforms[staid][tag].select(component=channel)
                    else:
                        st=self.waveforms[staid][tag]
                        st.rotate('NE->RT', backazimuth=baz) # need check
                        inST=st.select(component=channel)
                except KeyError: continue
                if len(inST)==0: continue
                else: tr=inST[0]
                stime=tr.stats.starttime; etime=tr.stats.endtime
                tr.stats.sac={}; tr.stats.sac['dist']= dist; tr.stats.sac['b']=stime-otime; tr.stats.sac['e']=etime-otime
                tr.stats.sac['kuser0']=evid
                aftanTr=pyaftan.aftantrace(tr.data, tr.stats)
                if verbose: print 'Preparing aftan data: ' + evid+' '+staid+'_'+channel
                inputStream.append(aftanTr)
        print 'Start multiprocessing aftan analysis !'
        if len(inputStream) > subsize:
            Nsub = int(len(inputStream)/subsize)
            for isub in xrange(Nsub):
                print 'Subset:', isub,'in',Nsub,'sets'
                cstream=inputStream[isub*subsize:(isub+1)*subsize]
                AFTAN = partial(aftan4mp_quake, outdir=outdir, inftan=inftan, prephdir=prephdir, f77=f77, pfx=pfx)
                pool = multiprocessing.Pool(processes=nprocess)
                pool.map(AFTAN, cstream) #make our results with a map call
                pool.close() #we are not adding any more processes
                pool.join() #tell it to wait until all threads are done before going on
            cstream=inputStream[(isub+1)*subsize:]
            AFTAN = partial(aftan4mp_quake, outdir=outdir, inftan=inftan, prephdir=prephdir, f77=f77, pfx=pfx)
            pool = multiprocessing.Pool(processes=nprocess)
            pool.map(AFTAN, cstream) #make our results with a map call
            pool.close() #we are not adding any more processes
            pool.join() #tell it to wait until all threads are done before going on
        else:
            AFTAN = partial(aftan4mp_quake, outdir=outdir, inftan=inftan, prephdir=prephdir, f77=f77, pfx=pfx)
            pool = multiprocessing.Pool(processes=nprocess)
            pool.map(AFTAN, inputStream) #make our results with a map call
            pool.close() #we are not adding any more processes
            pool.join() #tell it to wait until all threads are done before going on
        print 'End of multiprocessing aftan analysis !'
        print 'Reading aftan results into ASDF Dataset !'
        for event in self.events:
            for staid in staLst:
                netcode, stacode=staid.split('.')
                evid='E%05d' % evnumb
                finPR=pfx+'/'+evid+'/'+staid+'_'+channel+'.SAC'
                try:
                    f10=np.load(outdir+'/'+finPR+'_1_DISP.0.npz')
                    f11=np.load(outdir+'/'+finPR+'_1_DISP.1.npz')
                    f20=np.load(outdir+'/'+finPR+'_2_DISP.0.npz')
                    f21=np.load(outdir+'/'+finPR+'_2_DISP.1.npz')
                except IOError:
                    print 'NO aftan results: '+ evid+' '+staid+'_'+channel
                    continue
                if verbose: print 'Reading aftan results '+ evid+' '+staid+'_'+channel
                if deletedisp:
                    os.remove(outdir+'/'+finPR+'_1_DISP.0.npz')
                    os.remove(outdir+'/'+finPR+'_1_DISP.1.npz')
                    os.remove(outdir+'/'+finPR+'_2_DISP.0.npz')
                    os.remove(outdir+'/'+finPR+'_2_DISP.1.npz')
                arr1_1  = f10['arr_0']
                nfout1_1= f10['arr_1']
                arr2_1  = f11['arr_0']
                nfout2_1= f11['arr_1']
                arr1_2  = f20['arr_0']
                nfout1_2= f20['arr_1']
                arr2_2  = f21['arr_0']
                nfout2_2= f21['arr_1']
                staid_aux=evid+'/'+netcode+'_'+stacode+'_'+channel
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
        if deletedisp: shutil.rmtree(outdir+'/'+pfx)
        return
    
    def interp_disp(self, data_type='DISPpmf2', channel='Z', pers=np.array([]), verbose=True):
        """ Interpolate dispersion curve for a given period array.
        =======================================================================================================
        ::: input parameters :::
        data_type   - dispersion data type (default = DISPpmf2, pmf aftan results after jump detection)
        pers        - period array
        
        Output:
        self.auxiliary_data.DISPbasic1interp, self.auxiliary_data.DISPbasic2interp,
        self.auxiliary_data.DISPpmf1interp, self.auxiliary_data.DISPpmf2interp
        =======================================================================================================
        """
        if data_type=='DISPpmf2': ntype=6
        else: ntype=5
        if pers.size==0: pers=np.append( np.arange(7.)*2.+28., np.arange(6.)*5.+45.)
        staLst=self.waveforms.list()
        evnumb=0
        for event in self.events:
            evnumb+=1
            evid='E%05d' % evnumb
            for staid in staLst:
                netcode, stacode=staid.split('.')
                try:
                    subdset=self.auxiliary_data[data_type][evid][netcode+'_'+stacode+'_'+channel]
                except KeyError: continue
                data=subdset.data.value
                index=subdset.parameters
                if verbose: print 'Interpolating dispersion curve for '+ evid+' '+staid+'_'+channel
                outindex={ 'To': 0, 'Vgr': 1, 'Vph': 2,  'amp': 3, 'snr': 4, 'inbound': 5, 'Np': pers.size }
                Np=int(index['Np'])
                if Np < 5:
                    warnings.warn('Not enough datapoints for: '+ evid+' '+staid+'_'+channel, UserWarning, stacklevel=1)
                    continue
                obsT        = data[index['To']][:Np]
                Vgr         = np.interp(pers, obsT, data[index['Vgr']][:Np] )
                Vph         = np.interp(pers, obsT, data[index['Vph']][:Np] )
                amp         = np.interp(pers, obsT, data[index['amp']][:Np] )
                inbound     = (pers > obsT[0])*(pers < obsT[-1])*1
                interpdata  = np.append(pers, Vgr)
                interpdata  = np.append(interpdata, Vph)
                interpdata  = np.append(interpdata, amp)
                if data_type=='DISPpmf2':
                    snr     = np.interp(pers, obsT, data[index['snr']][:Np] )
                    interpdata=np.append(interpdata, snr)
                interpdata=np.append(interpdata, inbound)
                interpdata=interpdata.reshape(ntype, pers.size)
                staid_aux=evid+'/'+netcode+'_'+stacode+'_'+channel
                self.add_auxiliary_data(data=interpdata, data_type=data_type+'interp', path=staid_aux, parameters=outindex)
        return
    
    def quake_get_field(self, outdir=None, channel='Z', pers=np.array([]), data_type='DISPpmf2interp', verbose=True):
        """ Get the field data for Eikonal tomography
        ============================================================================================================================
        ::: input parameters :::
        outdir      - directory for txt output (default is not to generate txt output)
        channel     - channel name
        pers        - period array
        datatype    - dispersion data type (default = DISPpmf2interp, interpolated pmf aftan results after jump detection)
        Output:
        self.auxiliary_data.FieldDISPpmf2interp
        ============================================================================================================================
        """
        if pers.size==0: pers=np.append( np.arange(7.)*2.+28., np.arange(6.)*5.+45.)
        outindex={ 'longitude': 0, 'latitude': 1, 'Vph': 2,  'Vgr':3, 'amp': 4, 'snr': 5, 'dist': 6 }
        staLst=self.waveforms.list()
        evnumb=0
        for event in self.events:
            evnumb+=1
            evid='E%05d' % evnumb
            field_lst=[]
            Nfplst=[]
            for per in pers:
                field_lst.append(np.array([]))
                Nfplst.append(0)
            evlo=event.origins[0].longitude; evla=event.origins[0].latitude
            if verbose: print 'Getting field data for: '+evid
            for staid in staLst:
                netcode, stacode=staid.split('.')
                try: subdset=self.auxiliary_data[data_type][evid][netcode+'_'+stacode+'_'+channel]
                except KeyError: continue
                stla, stel, stlo=self.waveforms[staid].coordinates.values()
                az, baz, dist = geodist.inv(stlo, stla, evlo, evla); dist=dist/1000.
                if stlo<0: stlo+=360.
                if evlo<0: evlo+=360.
                data=subdset.data.value
                index=subdset.parameters
                for iper in xrange(pers.size):
                    per=pers[iper]
                    if dist < 2.*per*3.5: continue
                    ind_per=np.where(data[index['To']][:] == per)[0]
                    if ind_per.size==0: raise AttributeError('No interpolated dispersion curve data for period='+str(per)+' sec!')
                    pvel    = data[index['Vph']][ind_per]
                    gvel    = data[index['Vgr']][ind_per]
                    snr     = data[index['snr']][ind_per]
                    amp     = data[index['amp']][ind_per]
                    inbound = data[index['inbound']][ind_per]
                    # quality control
                    if pvel < 0 or gvel < 0 or pvel>10 or gvel>10 or snr >1e10: continue
                    if inbound!=1.: continue
                    if snr < 10.: continue # different from noise data
                    field_lst[iper] = np.append(field_lst[iper], stlo)
                    field_lst[iper] = np.append(field_lst[iper], stla)
                    field_lst[iper] = np.append(field_lst[iper], pvel)
                    field_lst[iper] = np.append(field_lst[iper], gvel)
                    field_lst[iper] = np.append(field_lst[iper], amp)
                    field_lst[iper] = np.append(field_lst[iper], snr)
                    field_lst[iper] = np.append(field_lst[iper], dist)
                    Nfplst[iper]+=1
            if outdir!=None:
                if not os.path.isdir(outdir): os.makedirs(outdir)
            staid_aux=evid+'_'+channel
            for iper in xrange(pers.size):
                per=pers[iper]
                del_per=per-int(per)
                if field_lst[iper].size==0: continue
                field_lst[iper]=field_lst[iper].reshape(Nfplst[iper], 7)
                if del_per==0.:
                    staid_aux_per=staid_aux+'/'+str(int(per))+'sec'
                else:
                    dper=str(del_per)
                    staid_aux_per=staid_aux+'/'+str(int(per))+'sec'+dper.split('.')[1]
                self.add_auxiliary_data(data=field_lst[iper], data_type='Field'+data_type, path=staid_aux_per, parameters=outindex)
                if outdir!=None:
                    if not os.path.isdir(outdir+'/'+str(per)+'sec'):
                        os.makedirs(outdir+'/'+str(per)+'sec')
                    txtfname=outdir+'/'+str(per)+'sec'+'/'+evid+'_'+str(per)+'.txt'
                    header = 'evlo='+str(evlo)+' evla='+str(evla)
                    np.savetxt( txtfname, field_lst[iper], fmt='%g', header=header )
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
        self.minlat=minlat; self.maxlat=maxlat; self.minlon=minlon; self.maxlon=maxlon
        return
    
    def get_ms(self, Vgr=None, period=10., wfactor=20., channel='Z', tb=0., outdir=None, inftan=pyaftan.InputFtanParam(), basic1=True, basic2=True, \
            pmf1=True, pmf2=True, verbose=True, prephdir=None, f77=True, pfx='DISP'):
        """Get surface wave magnitude according to Russell's formula
        Need polish 
        """
        print 'Start aftan analysis!'
        import obspy.signal
        staLst=self.waveforms.list()
        evnumb=0
        for event in self.events:
            evnumb+=1
            evlo=event.origins[0].longitude; evla=event.origins[0].latitude
            otime=event.origins[0].time
            tag='surf_ev_%05d' %evnumb
            evid='E%05d' % evnumb
            for staid in staLst:
                netcode, stacode=staid.split('.')
                stla, stz, stlo=self.waveforms[staid].coordinates.values()
                az, baz, dist = geodist.inv(evlo, evla, stlo, stla); dist=dist/1000. 
                if baz<0: baz+=360.
                try:
                    if channel!='R' and channel!='T':
                        inST=self.waveforms[staid][tag].select(component=channel)
                    else:
                        st=self.waveforms[staid][tag]
                        st.rotate('NE->RT', backazimuth=baz) 
                        inST=st.select(component=channel)
                except KeyError: continue
                if len(inST)==0: continue
                else: tr=inST[0]
                stime=tr.stats.starttime; etime=tr.stats.endtime
                tr.stats.sac={}; tr.stats.sac['dist']= dist; tr.stats.sac['b']=stime-otime; tr.stats.sac['e']=etime-otime
                aftanTr=pyaftan.aftantrace(tr.data, tr.stats)
                if prephdir !=None: phvelname = prephdir + "/%s.%s.pre" %(evid, staid)
                else: phvelname =''
                if f77:
                    aftanTr.aftanf77(pmf=inftan.pmf, piover4=inftan.piover4, vmin=inftan.vmin, vmax=inftan.vmax, tmin=inftan.tmin, tmax=inftan.tmax,
                        tresh=inftan.tresh, ffact=inftan.ffact, taperl=inftan.taperl, snr=inftan.snr, fmatch=inftan.fmatch, nfin=inftan.nfin,
                            npoints=inftan.npoints, perc=inftan.perc, phvelname=phvelname)
                else:
                    aftanTr.aftan(pmf=inftan.pmf, piover4=inftan.piover4, vmin=inftan.vmin, vmax=inftan.vmax, tmin=inftan.tmin, tmax=inftan.tmax,
                        tresh=inftan.tresh, ffact=inftan.ffact, taperl=inftan.taperl, snr=inftan.snr, fmatch=inftan.fmatch, nfin=inftan.nfin,
                            npoints=inftan.npoints, perc=inftan.perc, phvelname=phvelname)
                if verbose: print 'aftan analysis for: ' + evid+' '+staid+'_'+channel
                ###
                # measure Ms
                ###
                dist    = aftanTr.stats.sac.dist
                Delta   = obspy.geodetics.kilometer2degrees(dist)
                dt      = aftanTr.stats.delta
                fcorner = 0.6/period/np.sqrt(Delta)
                if Vgr==None:
                    obsTArr = aftanTr.ftanparam.arr2_2[1,:aftanTr.ftanparam.nfout2_2]
                    VgrArr  = aftanTr.ftanparam.arr2_2[2,:aftanTr.ftanparam.nfout2_2]
                    AmpArr  = aftanTr.ftanparam.arr2_2[7,:aftanTr.ftanparam.nfout2_2]
                    Vgr     = np.interp(period, obsTArr, VgrArr )
                    Amp     = np.interp(period, obsTArr, AmpArr )
                minT    = max(0., dist/Vgr-wfactor*period)
                maxT    = min(dist/Vgr+wfactor*period, aftanTr.stats.npts*dt)
                # minT    = max(0., dist/4.0)
                # maxT    = min(dist/2.5, aftanTr.stats.npts*dt)
                ntapb   = int(period/dt)
                ntape   = int(period/dt)
                nb      = int(minT/dt)
                ne      = int(maxT/dt)+1
                dataT   = aftanTr.taper(nb, ne, ntapb, ntape)
                tempTr  = aftanTr.copy()
                # print nb, ne
                # return dataT
                # tempTr.data=dataT[0]
                fmin=1./period-fcorner
                fmax=1./period+fcorner
                # print fcorner
                tempTr.filter('bandpass', freqmin=fmin, freqmax=fmax, corners=3, zerophase=True)
                # data_envelope = obspy.signal.filter.envelope(tempTr.data)
                # ab = data_envelope.max()
                ab=(np.abs(tempTr.data)).max()
                ab = ab * 1e9
                Ms=np.log10(ab) + 0.5*np.log10( np.sin(Delta*np.pi/180.) ) + 0.0031*((20./period)**1.8)*Delta\
                    - 0.66*np.log10(20./period)-np.log10(fcorner) # -0.43
                print  staid, ab, Ms, Vgr, Amp, dist, Delta
                # if staid == 'IC.HIA':return tempTr
        
def aftan4mp_quake(aTr, outdir, inftan, prephdir, f77, pfx):
    # print aTr.stats.network+'.'+aTr.stats.station
    if prephdir !=None:
        phvelname = prephdir + "/%s.%s.pre" %(aTr.stats.sac.kuser0, aTr.stats.network+'.'+aTr.stats.station)
    else:
        phvelname =''
    if f77:
        aTr.aftanf77(pmf=inftan.pmf, piover4=inftan.piover4, vmin=inftan.vmin, vmax=inftan.vmax, tmin=inftan.tmin, tmax=inftan.tmax,
            tresh=inftan.tresh, ffact=inftan.ffact, taperl=inftan.taperl, snr=inftan.snr, fmatch=inftan.fmatch, nfin=inftan.nfin,
                npoints=inftan.npoints, perc=inftan.perc, phvelname=phvelname)
    else:
        aTr.aftan(pmf=inftan.pmf, piover4=inftan.piover4, vmin=inftan.vmin, vmax=inftan.vmax, tmin=inftan.tmin, tmax=inftan.tmax,
            tresh=inftan.tresh, ffact=inftan.ffact, taperl=inftan.taperl, snr=inftan.snr, fmatch=inftan.fmatch, nfin=inftan.nfin,
                npoints=inftan.npoints, perc=inftan.perc, phvelname=phvelname)
    aTr.get_snr(ffact=inftan.ffact) # SNR analysis
    foutPR=outdir+'/'+pfx+'/'+aTr.stats.sac.kuser0+'/'+aTr.stats.network+'.'+aTr.stats.station+'_'+aTr.stats.channel[-1]+'.SAC'
    aTr.ftanparam.writeDISPbinary(foutPR)
    return


def get_waveforms4mp(reqinfo, outdir, client, pre_filt, verbose=True, rotation=False):
    try:
        try:
            st = client.get_waveforms(network=reqinfo.network, station=reqinfo.station, location=reqinfo.location, channel=reqinfo.channel,
                    starttime=reqinfo.starttime, endtime=reqinfo.endtime, attach_response=reqinfo.attach_response)
            st.detrend()
        except:
            if verbose:
                print 'No data for:', reqinfo.network+'.'+reqinfo.station
            return
        if verbose:
            print 'Getting data for:', reqinfo.network+'.'+reqinfo.station
        # print '===================================== Removing response ======================================='
        evid        = 'E%05d' %reqinfo.evnumb
        try:
            st.remove_response(pre_filt=pre_filt, taper_fraction=0.1)
        except :
            N       = 10
            i       = 0
            get_resp= False
            while (i < N) and (not get_resp):
                st  = client.get_waveforms(network=reqinfo.network, station=reqinfo.station, location=reqinfo.location, channel=reqinfo.channel,
                        starttime=reqinfo.starttime, endtime=reqinfo.endtime, attach_response=reqinfo.attach_response)
                try:
                    st.remove_response(pre_filt=pre_filt, taper_fraction=0.1)
                    get_resp    = True
                except :
                    i           += 1
            if not get_resp:
                st.write(outdir+'/'+evid+'.'+reqinfo.network+'.'+reqinfo.station+'.no_resp.mseed', format='mseed')
                return
        if rotation:
            st.rotate('NE->RT', back_azimuth=reqinfo.baz)
        st.write(outdir+'/'+evid+'.'+reqinfo.network+'.'+reqinfo.station+'.mseed', format='mseed')
    except:
        print 'Unknown error for:'+evid+'.'+reqinfo.network+'.'+reqinfo.station
    return

def ref4mp(refTr, outdir, inrefparam):
    refTr.IterDeconv(tdel=inrefparam.tdel, f0 = inrefparam.f0, niter=inrefparam.niter,
            minderr=inrefparam.minderr, phase=refTr.Ztr.stats.sac['kuser1'] )
    if not refTr.move_out():
        return
    refTr.stretch_back()
    refTr.save_data(outdir)
    return
