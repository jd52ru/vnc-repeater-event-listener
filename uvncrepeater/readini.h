#ifndef _READINI_H_
#define _READINI_H_

#include "commondefines.h"

//variables
extern int viewerPort;

extern int serverPort;

extern int allowedModes;

extern int loggingLevel;

extern bool useEventInterface;

extern int requireListedId;

extern int maxSessions;

extern int idList[];

extern char ownIpAddress[];

extern char runAsUser[];

extern char eventListenerHost[];

extern int eventListenerPort;

extern bool useHttpForEventListener;

//functions
bool readIniFile(char *iniFilePathAndName);

#endif