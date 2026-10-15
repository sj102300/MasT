#include "string_utils.h"

#include <cctype>

namespace strutil {

namespace {
bool isSpace(char c) { return c == ' ' || c == '\t' || c == '\r' || c == '\n'; }
}  // namespace

std::string trim(const std::string& s) {
    std::size_t begin = 0;
    std::size_t end = s.size();
    while (begin < end && isSpace(s[begin])) {
        ++begin;
    }
    while (end > begin && isSpace(s[end - 1])) {
        --end;
    }
    return s.substr(begin, end - begin);
}

std::vector<std::string> split(const std::string& s, char delimiter) {
    std::vector<std::string> parts;
    std::string current;
    for (char c : s) {
        if (c == delimiter) {
            parts.push_back(current);
            current.clear();
        } else {
            current += c;
        }
    }
    parts.push_back(current);
    return parts;
}

std::string toUpper(const std::string& s) {
    std::string out = s;
    for (char& c : out) {
        if (c >= 'a' && c <= 'z') {
            c = static_cast<char>(c - 'a' + 'A');
        }
    }
    return out;
}

bool startsWith(const std::string& s, const std::string& prefix) {
    return s.size() >= prefix.size() && s.compare(0, prefix.size(), prefix) == 0;
}

}  // namespace strutil
