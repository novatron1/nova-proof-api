from nova import NovaAdapter,Knowledge
k=Knowledge();k.add('dictionary','purchase','obtain something in exchange for payment','example-entry')
k.add('encyclopedia','thermal expansion','many materials expand when heated','example-entry')
n=NovaAdapter(knowledge=k)
for request in [
 {'task':'dictionary','term':'purchase'},
 {'task':'encyclopedia','term':'thermal expansion'},
 {'task':'calculate','expression':'15*120*8'},
 {'task':'prove','facts':['paid(marcus)'],'rules':[[['paid(marcus)'],'eligible(marcus)']],'goal':'eligible(marcus)'}]:
 print(request,'=>',n.process(request))
