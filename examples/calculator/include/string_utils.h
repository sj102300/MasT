#pragma once

#include <string>
#include <vector>

namespace strutil {

/// Removes leading and trailing whitespace (space, tab, CR, LF).
std::string trim(const std::string& s);

/// Splits s by delimiter. Empty fields are kept: split("a,,b", ',') -> {"a", "", "b"}.
std::vector<std::string> split(const std::string& s, char delimiter);

/// Converts ASCII letters to upper case; other characters are unchanged.
std::string toUpper(const std::string& s);

/// Returns true if s starts with prefix.
bool startsWith(const std::string& s, const std::string& prefix);

}  // namespace strutil
