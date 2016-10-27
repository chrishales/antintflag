from taskinit import *
import re
import numpy as np

# antintflag is released under a BSD 3-Clause License
# See LICENSE for details

# HISTORY:
#   1.0  27Oct2016  Initial version
#

def antintflag_getflagstats(vis,field,spw,spwmode,chan):
    if spwmode == True:
        casalog.filter('WARN')
        af.open(msname=vis)
        af.selectdata(field=str(field),spw=spw)
        ag0 = {'mode':'summary','action':'calculate'}
        af.parseagentparameters(ag0)
        af.init()
        temp = af.run(writeflags=False)
        af.done()
        casalog.filter('INFO')
        flagged = temp['report0']['flagged']
        total   = temp['report0']['total']
    else:
        # approach above can only get statistics per spw, not per channel
        casalog.filter('WARN')
        ms.open(vis)
        ms.msselect({'field':str(field),'spw':spw})
        temp_flag = ms.getdata('FLAG')['flag'][:,chan,:]
        #temp_flagrow = np.tile(ms.getdata('FLAG_ROW')['flag_row'],(temp_flag.shape[0],1))
        ms.close()
        casalog.filter('INFO')
        # note that casa currently does not respect flag_row!!
        # ie if flag_row is true and flag is false, tasks like
        # plotms will act as if the associated visibilities are
        # unflagged!!  This situation shouldn't turn up because
        # current consensus is that if flag_row needs to be set
        # to True, then all associated data in flag should also
        # be set to True.  However, I have found data where this
        # is indeed the case.  Cleaning this up remains an item
        # for CASA developers.  For this code, be safe and do
        # not take a logical OR here between flag_row and flag.
        # Instead, antintflag will only trust the flag column.
        #flagged = np.sum(np.logical_or(temp_flagrow,temp_flag))
        flagged = np.sum(temp_flag)
        total   = temp_flag.size
    
    return flagged , total

def antintflag(vis,field,spw,ant,minchanfrac,verbose):

    #
    # Task antintflag
    #
    #    Flags integrations if a specified antenna is flagged.
    #    
    #    Christopher A. Hales
    #    
    #    Version 1.0 (tested with CASA Version 4.7.0)
    #    27 October 2016
    
    casalog.origin('antintflag')
    casalog.post('--> antintflag version 1.0')
    
    if (minchanfrac < 0.) or (minchanfrac > 1.):
        casalog.post('*** ERROR: minchanfrac must be between 0-1.', 'ERROR')
        return
    
    tb.open(vis)
    if any('CORRECTED_DATA' in colnames for colnames in tb.colnames()):
        datacol='CORRECTED_DATA'
    else:
        datacol='DATA'
    
    tb.close()
    
    spwsplit = re.split(':',spw)
    if   (len(spwsplit)==1) and (spw.isdigit()):
        casalog.post('--> operating on '+datacol+' column in spectral window mode')
        spwmode = True
        # set dummy channel to simplify antintflag_getflagstats, channel never used
        chan = 0
    elif (len(spwsplit)==2) and (spwsplit[0].isdigit()) and (spwsplit[1].isdigit()):
        casalog.post('--> operating on '+datacol+' column in channel mode')
        spwmode = False
        spw  = spwsplit[0]
        chan = np.int(spwsplit[1])
    else:
        casalog.post('*** ERROR: Multiple spw index selection not supported.', 'ERROR')
        casalog.post('*** ERROR: Please specify only a single spw or single spw:chan.', 'ERROR')
        casalog.post('*** ERROR: Exiting antintflag.', 'ERROR')
        return
    
    # get number of baselines
    tb.open(vis+'/ANTENNA')
    atble=tb.getcol('NAME')
    antID=np.where(atble==ant)[0][0]
    tb.close()
    nant=atble.shape[0]
    nbaselines=nant*(nant-1)/2
    
    # get number of polarization products and channels in our spw
    tb.open(vis+'/DATA_DESCRIPTION')
    temptb=tb.query('SPECTRAL_WINDOW_ID='+spw)
    tb.close()
    polid=temptb.getcell('POLARIZATION_ID')
    tb.open(vis+'/POLARIZATION')
    npol=tb.getcell('NUM_CORR',polid)
    # don't need basis info
    tb.close()
    tb.open(vis+'/SPECTRAL_WINDOW')
    nchan=tb.getcell('NUM_CHAN',np.int(spw))
    tb.close()
    
    # get initial flagging statistics
    flagged1 , total = antintflag_getflagstats(vis,field,spw,spwmode,chan)
    
    # open MS and get timestamps
    casalog.filter('WARN')
    ms.open(vis,nomodify=False)
    ms.msselect({'field':str(field),'spw':spw})
    t = np.unique(ms.getdata('TIME')['time'])
    casalog.filter('INFO')
    timestamps = len(t)
    
    # go through timestamps
    flagtimestamp = 0
    casalog.post('--> status: 0% complete (updates delivered every 20%)')
    printupdate=np.ones(4).astype(bool)
    printcounter=1
    checkprint=True
    for i in range(timestamps):
        if checkprint:
            if printupdate[printcounter-1] and i+1>timestamps/5*printcounter:
                casalog.post('    status: '+str(20*printcounter)+'% complete')
                printupdate[printcounter-1]=False
                printcounter+=1
                if printcounter > 4:
                    checkprint=False
        
        # prec = 12 gives full double precision
        ymd = qa.time(qa.quantity(t[i],'s'),form='ymd',prec=12)[0]
        casalog.filter('WARN')
        ms.reset()
        ms.msselect({'field':str(field),'spw':spw,'time':ymd})
        # temp_flag is [npol,nchan,nbaselines]
        temp_flag = ms.getdata('FLAG')
        casalog.filter('INFO')
        # nbaselines rows should now be selected, test this
        # inefficient to test this every time?
        if temp_flag['flag'].shape[2] != nbaselines:
            casalog.post('*** ERROR: Your data is too complicated for antintflag.  Does it contain subscans?','ERROR')
            casalog.post('*** ERROR: Exiting antintflag.  Your data has not been modified.','ERROR')
            ms.close()
            return
        
        if spwmode:
            # no need to look at completely flagged timestamps
            if not (np.sum(temp_flag['flag']) == temp_flag['flag'].size):
                casalog.filter('WARN')
                temp_ant1 = ms.getdata('ANTENNA1')['antenna1']
                temp_ant2 = ms.getdata('ANTENNA2')['antenna2']
                casalog.filter('INFO')
                antROWS   = np.append(np.where(temp_ant2==antID)[0],np.where(temp_ant1==antID)[0])
                # antROWS.size should be nant-1, don't bother checking as we already did baseline check above
                flagged_chan = 0
                # inefficient loop, meh
                for k in range(nchan):
                    if np.sum(np.any(temp_flag['flag'][:,k,antROWS],axis=0)) == antROWS.size:
                        flagged_chan += 1
                
                if np.float(flagged_chan)/np.float(nchan) > minchanfrac:
                    temp_flag['flag'][:] = True
                    flagtimestamp += 1
                    if verbose:
                        casalog.post('            flagged integration at '+ymd)
        else:
            if not (np.sum(temp_flag['flag'][:,chan,:]) == temp_flag['flag'][:,chan,:].size):
                casalog.filter('WARN')
                temp_ant1 = ms.getdata('ANTENNA1')['antenna1']
                temp_ant2 = ms.getdata('ANTENNA2')['antenna2']
                casalog.filter('INFO')
                antROWS = np.append(np.where(temp_ant2==antID)[0],np.where(temp_ant1==antID)[0])
                if np.sum(np.any(temp_flag['flag'][:,chan,antROWS],axis=0)) == antROWS.size:
                    temp_flag['flag'][:] = True
                    flagtimestamp += 1
                    if verbose:
                        casalog.post('            flagged integration at '+ymd)
        
        ms.putdata(temp_flag)
    
    ms.close()
    casalog.post('    status: 100% complete (will now process flagging statistic)')
    
    # get final flagging stats
    flagged2 , total = antintflag_getflagstats(vis,field,spw,spwmode,chan)
    
    flag_frac = np.float(flagged2-flagged1)/total*100
    if flag_frac < 0.01:
        flag_fracS = "{:.1e}".format(flag_frac)
    else:
        flag_fracS = "{:.2f}".format(flag_frac)
    
    casalog.post('--> Number of integrations flagged = '+str(flagtimestamp)+'/'+str(timestamps))
    casalog.post('--> Fraction of data flagged = '+flag_fracS+'%')
