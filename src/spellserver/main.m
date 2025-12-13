/*
 * Shavian Spell Server - NSSpellServer service for English with Shavian support
 *
 * This service handles spell-checking for all English text, supporting both:
 * - Shavian script (𐑐-𐑿): Uses Hunspell dictionary with Shavian wordlist
 * - Latin script (a-z): Delegates to system English spell checker
 *
 * Users don't need to switch languages - the service automatically detects
 * the script and routes appropriately.
 */

#import <Foundation/Foundation.h>
#import "ShavianSpellChecker.h"

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        NSSpellServer *server = [[NSSpellServer alloc] init];
        ShavianSpellChecker *delegate = [[ShavianSpellChecker alloc] init];

        // Register all English variants we support
        // Each handles both Latin (delegated to system) and Shavian (our dictionary)
        NSArray *languages = @[
            @"English",
            @"en_US",  // US English
            @"en_GB",  // UK English (RP)
            @"en_AU",  // Australian English
            @"en_CA",  // Canadian English
            @"en_NZ"   // New Zealand English
        ];

        BOOL registered = NO;
        for (NSString *lang in languages) {
            if ([server registerLanguage:lang byVendor:@"ShawDict"]) {
                NSLog(@"ShavianSpellServer: Registered %@ spell checker", lang);
                registered = YES;
            } else {
                NSLog(@"ShavianSpellServer: Failed to register %@ spell checker", lang);
            }
        }

        if (registered) {
            // Set up our delegate to handle spell-checking requests for all variants
            [server setDelegate:delegate];

            // Run the spell server (this blocks)
            NSLog(@"ShavianSpellServer: Starting service...");
            [server run];

            NSLog(@"ShavianSpellServer: Service stopped");
        } else {
            NSLog(@"ShavianSpellServer: Failed to register any spell checkers");
            return 1;
        }
    }

    return 0;
}
