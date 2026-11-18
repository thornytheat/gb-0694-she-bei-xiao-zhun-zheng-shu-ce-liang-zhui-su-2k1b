CONCLUSION_ACCEPT='可采用'
CONCLUSION_REJECT='拒用'
CONCLUSION_RETEST='待复测'
DESTINATIONS={
    CONCLUSION_ACCEPT:'可采用，已计入可用测量',
    CONCLUSION_REJECT:'拒用，不得作为有效测量',
    CONCLUSION_RETEST:'待复测，需补交读数与误差带',
}

def apply(ctx):
     rows=[]
     for r in ctx['measurements']:
         chain=ctx['chains'][r['cert']];reasons=[]
         if not r['window_valid']:reasons.append('INVALID_WINDOW')
         state=r['range_state']
         if state=='OUT':reasons.append('OUT_OF_RANGE')
         elif state=='EDGE':reasons.append('EDGE_BAND')
         if not chain['valid']:reasons.append(chain['code'])
         blocking=[x for x in reasons if x!='EDGE_BAND']
         if blocking:conclusion=CONCLUSION_REJECT
         elif 'EDGE_BAND' in reasons:conclusion=CONCLUSION_RETEST
         else:conclusion=CONCLUSION_ACCEPT
         rows.append({'证书':r['cert'],'设备':r['canonical'],'测量值_V':r['value_v'],'误差带_V':'' if r.get('band_v') is None else r['band_v'],'测量日':r['measured_at'],'量程依据':r.get('range_basis_text',''),'结论':'待复测' if conclusion==CONCLUSION_RETEST else ('可采用' if conclusion==CONCLUSION_ACCEPT else '拒用'),'原因码':','.join(reasons) or 'ACCEPT','去向':DESTINATIONS[conclusion],'行号':r['行号']})
     ctx['verdicts']=rows;ctx['balanced']=ctx['input_count']==len(ctx['measurements'])+ctx['duplicates']+len(ctx['quarantine'])
     return {'rows':rows,'metrics':[['可采用',sum(r['结论']=='可采用' for r in rows),'条'],['拒用',sum(r['结论']=='拒用' for r in rows),'条'],['待复测',sum(r['结论']=='待复测' for r in rows),'条'],['行数守恒','相符' if ctx['balanced'] else '差异','']]}
