//
//  main.m
//  Shaw Spell Installer
//
//  Entry point for the Shaw Spell installer application.
//

#import <Cocoa/Cocoa.h>
#import "InstallerAppDelegate.h"

int main(int argc, const char * argv[]) {
    @autoreleasepool {
        NSApplication *app = [NSApplication sharedApplication];
        InstallerAppDelegate *delegate = [[InstallerAppDelegate alloc] init];
        [app setDelegate:delegate];
        [app run];
    }
    return 0;
}
