__all__ = ['f_version', 'i_version', 's_version', 'major_version', 'minor_version', 'sub_version']
f_version = 0.02
i_version = int(f_version * 100)
major_version, minor_version, sub_version = i_version // 100, i_version % 100 // 10, i_version % 10
s_version = "V{}.{}.{}".format(major_version, minor_version, sub_version)
