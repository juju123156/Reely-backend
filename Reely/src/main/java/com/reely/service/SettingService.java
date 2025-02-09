package com.reely.service;

import java.util.List;

import com.reely.dto.SettingDto;

public interface SettingService {

    List<SettingDto> getFaqList();

    List<SettingDto> getTermsList();

    List<SettingDto> getLatestVersion();
}
