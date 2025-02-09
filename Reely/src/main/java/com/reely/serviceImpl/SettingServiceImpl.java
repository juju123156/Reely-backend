package com.reely.serviceImpl;

import java.util.List;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.reely.dto.SettingDto;
import com.reely.mapper.SettingMapper;
import com.reely.service.SettingService;

@Transactional
@Service
public class SettingServiceImpl implements SettingService {

    private final SettingMapper settingMapper;

    @Autowired
    public SettingServiceImpl(SettingMapper settingRepository) {
        this.settingMapper = settingRepository;
    }
    @Override
    public List<SettingDto> getFaqList() {
        List<SettingDto>  faqList = settingMapper.findAll();
        return faqList;
    }
    @Override
    public List<SettingDto> getTermsList() {
        List<SettingDto>  termsList = settingMapper.getTermsList();
        return termsList;
    }
    @Override
    public List<SettingDto> getLatestVersion() {
        List<SettingDto>  latestVersion = settingMapper.getLatestVersion();
        return latestVersion;
    }
}
